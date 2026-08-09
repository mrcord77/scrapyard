"""
contract_signatory — Manage the set of signatories attached to a contract.

### PART-META-JSON
{
  "name": "contract_signatory",
  "layer": "legal",
  "purpose": "Track which users are signatories on which contracts: add_signatory()/remove_signatory() maintain unique (contract_id, user_id) rows with strict positive-int validation (bools rejected), get_signatories() returns the sorted user ids for a contract. Duplicate adds and missing removes raise ValueError.",
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "add_signatory(contract_id, user_id); remove_signatory(contract_id, user_id); get_signatories(contract_id). All ids must be positive ints.",
  "outputs": "ContractSignatory rows (unique per contract/user pair); get_signatories returns sorted list[int].",
  "files_created": ["scrapyard.db (SQLite in the current working directory) - only if the module is used without overriding the lazily-created default engine"],
  "security_notes": "This records WHO is listed as a signatory, not that anyone actually signed: there is no signature capture, verification, or timestamping - do not present these rows as executed-signature evidence. The lazy default engine writes sqlite:///scrapyard.db in the process CWD; production use must inject its own engine (the selftest swaps _engine) or you get an unmanaged world-readable file. No authentication: gate mutations behind contract-ownership checks in the composing app. Input validation rejects non-int and non-positive ids, limiting type-confusion abuse.",
  "ai_usage": "Point _engine at your configured engine (or accept the sqlite default for prototypes), create tables via ContractSignatory.metadata, then add_signatory(cid, uid).",
  "example": "from scrapyard.legal.contract_signatory import add_signatory, get_signatories",
  "import_path": "scrapyard.legal.contract_signatory"
}
### END-PART-META
"""

import logging
import os
import tempfile
import threading
from typing import Any

from sqlalchemy import Integer, UniqueConstraint, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

__all__ = [
    "ContractSignatory",
    "add_signatory",
    "get_signatories",
    "remove_signatory",
]


class ContractSignatory(IntPKModel):
    __tablename__ = "contract_signatory"
    __table_args__ = (UniqueConstraint("contract_id", "user_id", name="uix_contract_user"),)

    contract_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)


_engine = None
_engine_lock = threading.Lock()


def _get_engine() -> Any:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = create_engine("sqlite:///scrapyard.db", future=True, echo=False)
    return _engine


def _validate_id(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def add_signatory(contract_id: int, user_id: int) -> type(None):
    _validate_id(contract_id, "contract_id")
    _validate_id(user_id, "user_id")

    engine = _get_engine()
    with Session(engine) as session:
        existing = session.execute(
            select(ContractSignatory).where(
                ContractSignatory.contract_id == contract_id,
                ContractSignatory.user_id == user_id,
            )
        ).scalar_one_or_none()

        if existing is not None:
            raise ValueError("Signatory already exists for this contract")

        session.add(ContractSignatory(contract_id=contract_id, user_id=user_id))
        session.commit()


def remove_signatory(contract_id: int, user_id: int) -> type(None):
    _validate_id(contract_id, "contract_id")
    _validate_id(user_id, "user_id")

    engine = _get_engine()
    with Session(engine) as session:
        signatory = session.execute(
            select(ContractSignatory).where(
                ContractSignatory.contract_id == contract_id,
                ContractSignatory.user_id == user_id,
            )
        ).scalar_one_or_none()

        if signatory is None:
            raise ValueError("Signatory not found for this contract")

        session.delete(signatory)
        session.commit()


def get_signatories(contract_id: int) -> list[int]:
    _validate_id(contract_id, "contract_id")

    engine = _get_engine()
    with Session(engine) as session:
        rows = session.execute(
            select(ContractSignatory.user_id).where(
                ContractSignatory.contract_id == contract_id
            )
        ).scalars().all()

        return sorted(rows)


def _selftest() -> None:
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        db_path = os.path.join(tmpdir.name, "test_contract_signatory.db")
        engine = create_engine(f"sqlite:///{db_path}")

        global _engine
        previous_engine = _engine
        _engine = engine

        ContractSignatory.metadata.create_all(engine)

        # Type hints are present and correct
        assert add_signatory.__annotations__["contract_id"] is int
        assert add_signatory.__annotations__["user_id"] is int
        assert add_signatory.__annotations__["return"] is type(None)
        assert remove_signatory.__annotations__["contract_id"] is int
        assert remove_signatory.__annotations__["user_id"] is int
        assert remove_signatory.__annotations__["return"] is type(None)
        assert get_signatories.__annotations__["contract_id"] is int
        assert get_signatories.__annotations__["return"] == list[int]

        # Table structure
        table = ContractSignatory.__table__
        assert table.name == "contract_signatory"
        assert "contract_id" in table.columns
        assert "user_id" in table.columns

        # Invalid IDs raise exceptions
        bad_cases = [
            ("1", 1),
            (1, "1"),
            (0, 1),
            (1, 0),
            (-1, 1),
            (1, -1),
            (True, 1),
            (1, False),
        ]
        for bad_contract_id, bad_user_id in bad_cases:
            for func in (add_signatory, remove_signatory, get_signatories):
                if func is get_signatories and isinstance(bad_contract_id, int) and bad_contract_id > 0:
                    continue
                try:
                    func(bad_contract_id, bad_user_id)
                    raise AssertionError(f"Expected exception for {func.__name__}({bad_contract_id}, {bad_user_id})")
                except (TypeError, ValueError):
                    pass

        # Adding and retrieving signatories
        add_signatory(1, 10)
        add_signatory(1, 20)
        add_signatory(2, 30)
        assert get_signatories(1) == [10, 20]
        assert get_signatories(2) == [30]
        assert get_signatories(99) == []

        # Duplicate signatory
        try:
            add_signatory(1, 20)
            raise AssertionError("Expected ValueError for duplicate signatory")
        except ValueError:
            pass

        # Removing signatories
        remove_signatory(1, 10)
        assert get_signatories(1) == [20]

        # Removing absent signatory
        try:
            remove_signatory(1, 10)
            raise AssertionError("Expected ValueError for missing signatory")
        except ValueError:
            pass

        # No side effects on default database path
        assert not os.path.exists("scrapyard.db")

    finally:
        engine.dispose()
        _engine = previous_engine
        tmpdir.cleanup()


if __name__ == "__main__":
    _selftest()
