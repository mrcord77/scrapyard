"""
slot_searcher — Enables efficient search and filtering of scheduling slots based on time, resource, and status. Supports complex queries for meeting scheduling systems requiring dynamic slot selection.

### PART-META-JSON
{
  "name": "slot_searcher",
  "layer": "scheduling",
  "purpose": "Enables efficient search and filtering of scheduling slots based on time, resource, and status. Supports overlap queries for meeting scheduling systems requiring dynamic slot selection. Uses the canonical Slot model owned by scrapyard.scheduling.slot_manager (no model of its own).",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.scheduling.slot_manager"],
  "inputs": "SQLAlchemy Session, time-range datetimes, resource_id, status string.",
  "outputs": "Lists of slot_manager.Slot rows matching the filters.",
  "files_created": [],
  "security_notes": "Read-only queries with no authorization filter: results include every matching slot regardless of caller, so apply tenant/user scoping before exposing results. Status strings are matched exactly as passed (parameterized, no SQL injection risk).",
  "ai_usage": "Import what you need from `scrapyard.scheduling.slot_searcher`.",
  "example": "from scrapyard.scheduling.slot_searcher import *",
  "import_path": "scrapyard.scheduling.slot_searcher"
}
### END-PART-META
"""

from sqlalchemy import select
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from typing import List
import logging

# Canonical-owner pattern: slot_manager owns the Slot model for the
# scheduling layer; this part imports it instead of declaring a duplicate.
from scrapyard.scheduling.slot_manager import Slot

logger = logging.getLogger(__name__)


def search_slots(session: Session, start: datetime, end: datetime, resource_id: int) -> List[Slot]:
    """Search for slots overlapping with the given time range for a specific resource."""
    stmt = select(Slot).where(
        Slot.resource_id == resource_id,
        Slot.start < end,
        Slot.end > start
    )
    return list(session.execute(stmt).scalars().all())


def filter_slots_by_status(session: Session, status: str) -> List[Slot]:
    """Filter slots by their status."""
    stmt = select(Slot).where(Slot.status == status)
    return list(session.execute(stmt).scalars().all())


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    import tempfile
    import os
    from sqlalchemy import create_engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        Slot.metadata.create_all(engine)
        
        with Session(engine) as session:
            now = datetime.now(timezone.utc)
            
            slot1 = Slot(
                start=now,
                end=now + timedelta(hours=1),
                resource_id=1,
                status="available"
            )
            slot2 = Slot(
                start=now + timedelta(hours=2),
                end=now + timedelta(hours=3),
                resource_id=1,
                status="booked"
            )
            slot3 = Slot(
                start=now,
                end=now + timedelta(hours=1),
                resource_id=2,
                status="available"
            )
            
            session.add_all([slot1, slot2, slot3])
            session.commit()
            
            results = search_slots(session, now, now + timedelta(minutes=30), 1)
            assert len(results) == 1
            assert results[0].resource_id == 1
            assert results[0].status == "available"
            
            results = search_slots(session, now + timedelta(hours=2), now + timedelta(hours=4), 1)
            assert len(results) == 1
            assert results[0].status == "booked"
            
            results = search_slots(session, now, now + timedelta(hours=2), 2)
            assert len(results) == 1
            assert results[0].resource_id == 2
            
            results = search_slots(session, now, now + timedelta(hours=2), 999)
            assert len(results) == 0
            
            available_slots = filter_slots_by_status(session, "available")
            assert len(available_slots) == 2
            assert all(s.status == "available" for s in available_slots)
            
            booked_slots = filter_slots_by_status(session, "booked")
            assert len(booked_slots) == 1
            assert booked_slots[0].status == "booked"
            
            assert not session.dirty
            assert not session.new

        engine.dispose()


if __name__ == "__main__":
    _selftest()
