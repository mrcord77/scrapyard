"""
validity_window - Time-bound validity for quoting artifacts (proposals, line items, pricing tiers) with expiry checks and extension.

### PART-META-JSON
{
  "name": "validity_window",
  "layer": "quoting",
  "purpose": "Time-bound validity for quoting artifacts (proposals, line items, pricing tiers) with expiry checks and extension.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "is_valid(window, now); check_validity_period(window, now); extend_validity(window, days, session).",
  "outputs": "ValidityWindow rows (table 'validity_windows'); validity booleans and reason strings.",
  "files_created": [],
  "security_notes": "Prevents acceptance of stale quotes: expiry checks compare caller-supplied 'now' against stored bounds - pass a trusted clock (server UTC), never a client timestamp, or expiry can be bypassed. extend_validity mutates windows; gate it behind authorization upstream.",
  "ai_usage": "Import what you need from `scrapyard.quoting.validity_window`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.quoting.validity_window import is_valid",
  "import_path": "scrapyard.quoting.validity_window"
}
### END-PART-META
"""
"""
scrapyard.quoting.validity_window

Manages time-bound validity of quoting data, ensuring proposals, line items, 
and pricing tiers remain valid within defined periods.
"""

import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import DateTime, Integer, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker, validates

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class ValidityWindow(IntPKModel):
    """Represents a validity window for quoting entities."""
    
    __tablename__ = "validity_windows"
    
    start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    proposal_id: Mapped[int] = mapped_column(Integer, nullable=False)
    line_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pricing_tier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    @validates('start', 'end')
    def validate_dates(self, key: str, value: datetime) -> datetime:
        """Ensure start < end at the object level."""
        if key == 'start':
            if self.end is not None and value >= self.end:
                raise ValueError("start must be before end")
        elif key == 'end':
            if self.start is not None and value <= self.start:
                raise ValueError("end must be after start")
        return value
    
    def __repr__(self) -> str:
        return (
            f"<ValidityWindow(id={self.id}, start={self.start}, "
            f"end={self.end}, proposal_id={self.proposal_id})>"
        )


def is_valid(window: ValidityWindow, now: datetime) -> bool:
    """
    Check if the given datetime falls within the validity window.
    
    Args:
        window: The validity window to check against
        now: The datetime to validate (typically current time)
        
    Returns:
        True if now is within [start, end] inclusive, False otherwise
    """
    return window.start <= now <= window.end


def check_validity_period(window: ValidityWindow, now: datetime) -> Tuple[bool, str]:
    """
    Check validity and return detailed status.
    
    Args:
        window: The validity window to check
        now: The datetime to check against
        
    Returns:
        Tuple of (is_valid: bool, message: str)
    """
    if now < window.start:
        return False, f"Validity period has not started yet (starts at {window.start})"
    elif now > window.end:
        return False, f"Validity period has expired (ended at {window.end})"
    else:
        return True, "Validity period is active"


def extend_validity(window: ValidityWindow, days: int, session: Session) -> None:
    """
    Extend the validity window by adding days to the end timestamp.
    
    Args:
        window: The validity window to extend
        days: Number of days to add (must be non-negative)
        session: SQLAlchemy session for persistence
        
    Raises:
        ValueError: If days is negative
    """
    if days < 0:
        raise ValueError("Days to extend must be non-negative")
    
    window.end = window.end + timedelta(days=days)
    session.add(window)
    session.commit()


def _selftest() -> None:
    """
    Offline self-test suite using temporary SQLite database.
    Validates all public API functions and model constraints.
    """
    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        if isinstance(dbapi_conn, sqlite3.Connection):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_validity.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        IntPKModel.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        try:
            reference_time = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
            
            # Test: Validity check returns False when before window
            window_future = ValidityWindow(
                start=datetime(2024, 7, 1, 0, 0, 0, tzinfo=timezone.utc),
                end=datetime(2024, 7, 31, 0, 0, 0, tzinfo=timezone.utc),
                proposal_id=1
            )
            assert is_valid(window_future, reference_time) is False
            
            # Test: Validity check returns False when after window
            window_past = ValidityWindow(
                start=datetime(2024, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
                end=datetime(2024, 5, 31, 0, 0, 0, tzinfo=timezone.utc),
                proposal_id=2
            )
            assert is_valid(window_past, reference_time) is False
            
            # Test: Validity check returns True when inside window
            window_current = ValidityWindow(
                start=datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
                end=datetime(2024, 6, 30, 0, 0, 0, tzinfo=timezone.utc),
                proposal_id=3,
                line_item_id=100
            )
            assert is_valid(window_current, reference_time) is True
            
            # Test: check_validity_period returns correct tuples
            valid, msg = check_validity_period(window_current, reference_time)
            assert valid is True and "active" in msg
            
            valid, msg = check_validity_period(window_future, reference_time)
            assert valid is False and ("not started" in msg or "starts at" in msg)
            
            valid, msg = check_validity_period(window_past, reference_time)
            assert valid is False and ("expired" in msg or "ended at" in msg)
            
            # Test: extend_validity updates end timestamp correctly
            session.add(window_current)
            session.commit()
            
            original_end = window_current.end
            extend_validity(window_current, 7, session)
            session.refresh(window_current)
            
            assert window_current.end == original_end + timedelta(days=7)
            
            # Test: extend_validity raises ValueError for negative days
            try:
                extend_validity(window_current, -1, session)
                assert False, "Expected ValueError for negative days"
            except ValueError as e:
                assert "non-negative" in str(e).lower()
            
            # Test: Model constraints enforce start < end (creation time)
            try:
                invalid_window = ValidityWindow(
                    start=datetime(2024, 6, 20, 0, 0, 0, tzinfo=timezone.utc),
                    end=datetime(2024, 6, 10, 0, 0, 0, tzinfo=timezone.utc),
                    proposal_id=4
                )
                assert False, "Expected ValueError for end before start"
            except ValueError as e:
                assert "after start" in str(e).lower()
            
            # Test: Model constraints enforce start < end (mutation)
            window_test = ValidityWindow(
                start=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                end=datetime(2024, 1, 31, 0, 0, 0, tzinfo=timezone.utc),
                proposal_id=5
            )
            try:
                window_test.start = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
                assert False, "Expected ValueError when setting start after end"
            except ValueError:
                pass
            
            # Test: Optional fields can be None
            window_minimal = ValidityWindow(
                start=datetime(2024, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
                end=datetime(2024, 3, 31, 0, 0, 0, tzinfo=timezone.utc),
                proposal_id=6,
                line_item_id=None,
                pricing_tier_id=None
            )
            session.add(window_minimal)
            session.commit()
            assert window_minimal.id is not None
            assert window_minimal.line_item_id is None
            assert window_minimal.pricing_tier_id is None
            
        finally:
            session.close()
            engine.dispose()
            try:
                os.unlink(db_path)
            except OSError:
                pass


if __name__ == "__main__":
    _selftest()
    print("validity_window selftest OK")
