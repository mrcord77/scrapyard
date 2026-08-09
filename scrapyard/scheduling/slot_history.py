"""
slot_history — ** Tracks historical changes to scheduling slots for auditing and reporting. Provides immutable, versioned records of slot modifications.

### PART-META-JSON
{
  "name": "slot_history",
  "layer": "scheduling",
  "purpose": "Tracks historical changes to scheduling slots for auditing and reporting. Provides immutable, versioned records of slot modifications.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: log_slot_change(slot_id, change_type, details, *, session, user_id); get_slot_history(slot_id, *, session); SlotHistory(...).",
  "outputs": "Returns: log_slot_change -> None; get_slot_history -> List[SlotHistory].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.scheduling.slot_history`.",
  "example": "from scrapyard.scheduling.slot_history import *",
  "import_path": "scrapyard.scheduling.slot_history"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, DateTime, Integer, String, create_engine, inspect, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

PART_META = {
    "name": "slot_history",
    "layer": "scheduling"
}


class SlotHistory(IntPKModel):
    """Immutable history record for scheduling slot changes."""
    
    __tablename__ = "slot_history"
    
    slot_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    change_type: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    def __repr__(self) -> str:
        return (
            f"<SlotHistory(id={self.id}, slot_id={self.slot_id}, "
            f"change_type='{self.change_type}', created_at='{self.created_at}')>"
        )


def _validate_log_inputs(slot_id: int, change_type: str, details: dict) -> None:
    """Validate inputs for logging slot changes."""
    if not isinstance(slot_id, int):
        raise TypeError(f"slot_id must be int, got {type(slot_id).__name__}")
    if not isinstance(change_type, str):
        raise TypeError(f"change_type must be str, got {type(change_type).__name__}")
    if not isinstance(details, dict):
        raise TypeError(f"details must be dict, got {type(details).__name__}")
    if not change_type:
        raise ValueError("change_type must be a non-empty string")


def log_slot_change(
    slot_id: int,
    change_type: str,
    details: dict,
    *,
    session: Optional[Session] = None,
    user_id: Optional[int] = None
) -> None:
    """
    Log a historical change to a scheduling slot.
    
    Args:
        slot_id: Identifier of the slot being modified
        change_type: Categorical type of change (e.g., 'created', 'updated', 'deleted')
        details: Serializable dictionary containing change payload
        session: SQLAlchemy Session to add the record to. Must be provided.
        user_id: Optional identifier of the user making the change
    
    Raises:
        TypeError: If slot_id, change_type, or details have incorrect types
        RuntimeError: If no session is provided
    """
    _validate_log_inputs(slot_id, change_type, details)
    
    if session is None:
        raise RuntimeError("A SQLAlchemy Session is required to log slot changes")
    
    record = SlotHistory(
        slot_id=slot_id,
        change_type=change_type,
        details=details,
        user_id=user_id
    )
    session.add(record)
    # Intentionally do not commit here; caller manages transaction boundaries


def get_slot_history(
    slot_id: int,
    *,
    session: Optional[Session] = None
) -> List[SlotHistory]:
    """
    Retrieve historical changes for a specific slot.
    
    Args:
        slot_id: Identifier of the slot to query
        session: SQLAlchemy Session to use for querying. Must be provided.
        
    Returns:
        List of SlotHistory records ordered by creation time (newest first)
    
    Raises:
        TypeError: If slot_id is not an integer
        RuntimeError: If no session is provided
    """
    if not isinstance(slot_id, int):
        raise TypeError(f"slot_id must be int, got {type(slot_id).__name__}")
    
    if session is None:
        raise RuntimeError("A SQLAlchemy Session is required to retrieve slot history")
    
    stmt = (
        select(SlotHistory)
        .where(SlotHistory.slot_id == slot_id)
        .order_by(SlotHistory.created_at.desc(), SlotHistory.id.desc())
    )
    return list(session.scalars(stmt))


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "slot_history_test.db")
        engine = create_engine(f"sqlite:///{db_path}", future=True, echo=False)
        
        # Verify schema creation
        IntPKModel.metadata.create_all(engine)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "slot_history" in tables, "slot_history table was not created"
        
        columns = {col["name"]: col for col in inspector.get_columns("slot_history")}
        required_cols = {"id", "slot_id", "change_type", "details", "created_at", "user_id"}
        assert required_cols.issubset(columns.keys()), f"Missing columns: {required_cols - columns.keys()}"
        assert isinstance(columns["details"]["type"], JSON), "details column should be JSON type"
        
        SessionFactory = sessionmaker(bind=engine, future=True)
        
        # Test type enforcement
        with SessionFactory() as session:
            try:
                log_slot_change("not an int", "test", {}, session=session)
                assert False, "Should raise TypeError for non-int slot_id"
            except TypeError:
                pass
            
            try:
                log_slot_change(1, 123, {}, session=session)
                assert False, "Should raise TypeError for non-str change_type"
            except TypeError:
                pass
            
            try:
                log_slot_change(1, "test", "not a dict", session=session)
                assert False, "Should raise TypeError for non-dict details"
            except TypeError:
                pass
            
            try:
                log_slot_change(1, "", {}, session=session)
                assert False, "Should raise ValueError for empty change_type"
            except ValueError:
                pass
        
        # Test logging and retrieval with session-based persistence
        with SessionFactory() as session:
            # Log changes without committing immediately (session-based persistence)
            log_slot_change(
                slot_id=100,
                change_type="created",
                details={"capacity": 50, "location": "Zone A"},
                session=session,
                user_id=42
            )
            log_slot_change(
                slot_id=100,
                change_type="updated",
                details={"capacity": 75},
                session=session,
                user_id=43
            )
            log_slot_change(
                slot_id=200,
                change_type="created",
                details={"capacity": 100},
                session=session
                # user_id intentionally omitted (nullable)
            )
            
            # Verify records are pending (not yet committed)
            assert len(session.new) == 3, "Expected 3 pending records in session"
            
            # Commit
            session.commit()
        
        # Verify retrieval after commit
        with SessionFactory() as session:
            history_100 = get_slot_history(100, session=session)
            assert len(history_100) == 2, f"Expected 2 records for slot 100, got {len(history_100)}"
            assert history_100[0].change_type == "updated"  # descending order
            assert history_100[1].change_type == "created"
            assert history_100[0].details == {"capacity": 75}
            assert history_100[0].user_id == 43
            assert history_100[1].user_id == 42
            assert isinstance(history_100[0].created_at, datetime)
            
            history_200 = get_slot_history(200, session=session)
            assert len(history_200) == 1
            assert history_200[0].user_id is None
            
            history_empty = get_slot_history(999, session=session)
            assert history_empty == []
        
        # Cleanup
        engine.dispose()
    
    elapsed = time.time() - start_time
    assert elapsed < 20, f"Self-test exceeded 20 seconds: {elapsed:.2f}s"
    logger.info(f"_selftest passed in {elapsed:.2f}s")


if __name__ == "__main__":
    _selftest()
