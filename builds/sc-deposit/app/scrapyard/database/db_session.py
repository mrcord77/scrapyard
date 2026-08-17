"""
db_session — SQLAlchemy engine + session factory + get_db dependency.

### PART-META-JSON
{
  "name": "db_session",
  "layer": "database",
  "purpose": "SQLAlchemy engine + session factory + get_db dependency.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: init_engine(database_url, *, echo); get_sessionmaker(); get_db(); session_scope().",
  "outputs": "Returns: get_db -> Iterator; session_scope -> Iterator.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `init_engine` from `scrapyard.database.db_session` and call it as shown in `example`; run `py -m scrapyard.database.db_session` to see its offline selftest.",
  "example": "from scrapyard.database.db_session import init_engine",
  "import_path": "scrapyard.database.db_session"
}
### END-PART-META
"""
from __future__ import annotations
from contextlib import contextmanager
from typing import Iterator

STATUS = "core"

_engine = None
_SessionLocal = None


def init_engine(database_url: str, *, echo: bool = False):
    """Create the engine + session factory once. Returns the engine."""
    global _engine, _SessionLocal
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    kw = {"echo": echo, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(database_url, **kw)
    if database_url.startswith("sqlite"):
        # SQLite ignores FOREIGN KEY constraints unless told to enforce them per
        # connection — without this, referential integrity is silently off in dev/test.
        from sqlalchemy import event

        @event.listens_for(_engine, "connect")
        def _fk_pragma(dbapi_conn, _rec):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_sessionmaker():
    """Return the configured session factory (after init_engine)."""
    if _SessionLocal is None:
        raise RuntimeError("call init_engine(database_url) at startup first")
    return _SessionLocal


def get_db() -> Iterator:
    """FastAPI dependency yielding a session, closed after the request."""
    if _SessionLocal is None:
        raise RuntimeError("call init_engine(database_url) at startup first")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator:
    """Transactional scope: commit on success, rollback on error."""
    if _SessionLocal is None:
        raise RuntimeError("call init_engine(database_url) at startup first")
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _selftest() -> None:
    from sqlalchemy import String, Column, select, func
    from scrapyard.database.base_model import Base, IntPKModel

    global _engine, _SessionLocal
    _engine = None; _SessionLocal = None
    try:                                                  # negative: factory before init fails loudly
        get_sessionmaker()
        raise AssertionError("get_sessionmaker worked before init_engine")
    except RuntimeError:
        pass

    class Thing(IntPKModel):                              # imperative column: no annotation eval needed
        __tablename__ = "db_session_selftest_thing"
        name = Column(String(20))

    engine = init_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert get_sessionmaker() is _SessionLocal

    def n():
        with session_scope() as s:
            return s.scalar(select(func.count()).select_from(Thing))

    with session_scope() as s:                            # commits on success
        s.add(Thing(name="x"))
    assert n() == 1

    try:                                                  # rolls back on error -> row absent
        with session_scope() as s:
            s.add(Thing(name="y")); s.flush()
            raise ValueError("boom")
    except ValueError:
        pass
    assert n() == 1
    print("db_session selftest: PASS")


if __name__ == "__main__":
    _selftest()
