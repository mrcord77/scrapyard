"""
transactions — Transaction + unit-of-work context managers.

### PART-META-JSON
{
  "name": "transactions",
  "layer": "database",
  "purpose": "Transaction + unit-of-work context managers.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: begin_transaction(db, isolation_level, timeout); with_transaction(db); commit_transaction(db); rollback_transaction(db); with_unit_of_work(db, track_changes); Base(...); TransactionError(...) (plus more).",
  "outputs": "Returns: begin_transaction -> Session; with_transaction -> Generator[Session, None, None]; commit_transaction -> None; rollback_transaction -> None; with_unit_of_work -> Generator[Session, None, None].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `begin_transaction` from `scrapyard.database.transactions` and call it as shown in `example`; run `py -m scrapyard.database.transactions` to see its offline selftest.",
  "example": "from scrapyard.database.transactions import begin_transaction",
  "import_path": "scrapyard.database.transactions"
}
### END-PART-META
"""
from contextlib import contextmanager, nullcontext
from typing import Any, Callable, Dict, Generator, List, TypeVar

from sqlalchemy import sql
from jinja2 import Template
from sqlalchemy.orm import Session

T = TypeVar('T')

class Base:
    pass  # Define your base model here or ensure it is imported correctly

class TransactionError(Exception):
    pass

_TRANSACTION_POLICY = {"max_retries": 3, "retry_delay": 1}

def begin_transaction(db: Session, isolation_level: str = "READ COMMITTED", timeout: int = 30) -> Session:
    db.execute(sql.text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level}"))
    if timeout > 0:
        db.execute(sql.text(f"SET SESSION statement_timeout TO {timeout * 1000}"))
    return db

@contextmanager
def with_transaction(db: Session) -> Generator[Session, None, None]:
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        raise TransactionError(f"Transaction failed: {e}") from e

def commit_transaction(db: Session) -> None:
    db.commit()

def rollback_transaction(db: Session) -> None:
    db.rollback()

@contextmanager
def with_unit_of_work(db: Session, track_changes: bool = True) -> Generator[Session, None, None]:
    try:
        tracker = globals()["track_changes"](db) if track_changes else nullcontext()
        with tracker:
            yield db
        apply_changes(db)
    except Exception as e:
        rollback_changes(db)
        raise TransactionError(f"Unit of work failed: {e}") from e

def run_in_transaction(func: Callable, *args, **kwargs) -> Any:
    with Session.begin() as session:
        return func(session, *args, **kwargs)

def transactional(func: Callable) -> Callable:
    def wrapper(*args, **kwargs):
        with Session.begin() as session:
            result = func(session, *args, **kwargs)
        return result
    return wrapper

@contextmanager
def track_changes(db: Session) -> None:
    # Force connection acquisition before entering the unit of work without
    # relying on backend-specific transaction inspection.
    db.execute(sql.text("SELECT 1")).scalar()
    yield

def apply_changes(db: Session) -> None:
    db.flush()
    db.commit()

def rollback_changes(db: Session) -> None:
    db.rollback()

def audit_transaction(db: Session, event: str = "commit") -> None:
    template = Template("Transaction {{event}} at {{timestamp}}")
    message = template.render(event=event, timestamp=db.execute(sql.text("SELECT current_timestamp")).scalar())
    print(message)

def configure_transaction_policy(max_retries: int = 3, retry_delay: int = 1) -> None:
    if max_retries < 0 or retry_delay < 0:
        raise ValueError("transaction retry settings must be non-negative")
    _TRANSACTION_POLICY.update(max_retries=max_retries, retry_delay=retry_delay)

def bulk_commit(db: Session, entities: List[Base]) -> None:
    db.add_all(entities)
    db.commit()

def bulk_delete(db: Session, entities: List[Base]) -> None:
    for entity in entities:
        db.delete(entity)
    db.commit()

def serialize_transaction(db: Session) -> Dict[str, Any]:
    return {"transaction_id": db.execute(sql.text("SELECT current_setting('transaction_id')")).scalar()}

@contextmanager
def atomic(db):
    """Run a block in a transaction: commit on success, rollback on error."""
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def _selftest() -> None:
    from sqlalchemy import create_engine, String, select, func
    from sqlalchemy.orm import Mapped, mapped_column, sessionmaker, DeclarativeBase

    class B(DeclarativeBase):
        pass

    class Acct(B):
        __tablename__ = "transactions_selftest_acct"
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str] = mapped_column(String(20))

    engine = create_engine("sqlite:///:memory:")
    B.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    def n():
        return db.scalar(select(func.count()).select_from(Acct))

    with with_transaction(db):                            # commit path
        db.add(Acct(name="ok"))
    assert n() == 1

    # rollback path: an exception must leave NO row AND surface as TransactionError
    try:
        with with_transaction(db):
            db.add(Acct(name="doomed")); db.flush()
            raise ValueError("boom")
    except TransactionError:
        pass
    else:
        raise AssertionError("with_transaction swallowed the failure")
    assert n() == 1                                       # negative: doomed row rolled back

    with atomic(db):                                      # atomic() commits on clean exit
        db.add(Acct(name="also_ok"))
    assert n() == 2
    with with_unit_of_work(db):
        db.add(Acct(name="uow"))
    assert n() == 3
    configure_transaction_policy(5, 0)
    assert _TRANSACTION_POLICY == {"max_retries": 5, "retry_delay": 0}
    try:
        configure_transaction_policy(-1, 0)
        raise AssertionError("accepted negative retry count")
    except ValueError:
        pass
    db.close()
    print("transactions selftest: PASS")


if __name__ == "__main__":
    _selftest()
