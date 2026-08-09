"""
resource_calendar — Track resource availability and unavailability periods for scheduling. Enables precise time-based allocation and conflict detection in resource-scheduling systems.

### PART-META-JSON
{
  "name": "resource_calendar",
  "layer": "projects",
  "purpose": "Track resource availability and unavailability periods for scheduling. Enables precise time-based allocation and conflict detection in resource-scheduling systems.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: add_availability(session, resource_id, start, end, recurrence_rule); add_unavailability(session, resource_id, start, end, recurrence_rule); CalendarEntry(...); ConflictError(...).",
  "outputs": "Returns: add_availability -> CalendarEntry; add_unavailability -> CalendarEntry.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.resource_calendar`.",
  "example": "from scrapyard.projects.resource_calendar import *",
  "import_path": "scrapyard.projects.resource_calendar"
}
### END-PART-META
"""

import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, String, Boolean, Integer, Index, select, and_, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class CalendarEntry(IntPKModel):
    """ORM model for resource availability calendar entries."""
    
    __tablename__ = "calendar_entries"
    
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    recurrence_rule: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    __table_args__ = (
        Index('idx_calendar_resource_time', 'resource_id', 'start', 'end'),
        Index('idx_calendar_deleted', 'deleted_at'),
    )


class ConflictError(Exception):
    """Raised when a calendar entry conflicts with existing entries."""
    pass


def _check_overlap(session: Session, resource_id: int, start: datetime, end: datetime,
                   exclude_id: Optional[int] = None) -> bool:
    """Check if interval overlaps with any existing non-deleted entry for resource."""
    stmt = select(CalendarEntry).where(
        and_(
            CalendarEntry.resource_id == resource_id,
            CalendarEntry.deleted_at.is_(None),
            CalendarEntry.start < end,
            CalendarEntry.end > start
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(CalendarEntry.id != exclude_id)
    
    return session.execute(stmt).first() is not None


def add_availability(session: Session, resource_id: int, start: datetime, end: datetime,
                     recurrence_rule: Optional[str] = None) -> CalendarEntry:
    """Add an availability interval for a resource."""
    if _check_overlap(session, resource_id, start, end):
        raise ConflictError(f"Availability conflicts with existing entry for resource {resource_id}")
    
    entry = CalendarEntry(
        resource_id=resource_id,
        start=start,
        end=end,
        is_available=True,
        recurrence_rule=recurrence_rule,
        deleted_at=None
    )
    session.add(entry)
    session.flush()
    return entry


def add_unavailability(session: Session, resource_id: int, start: datetime, end: datetime,
                       recurrence_rule: Optional[str] = None) -> CalendarEntry:
    """Add an unavailability interval for a resource."""
    if _check_overlap(session, resource_id, start, end):
        raise ConflictError(f"Unavailability conflicts with existing entry for resource {resource_id}")
    
    entry = CalendarEntry(
        resource_id=resource_id,
        start=start,
        end=end,
        is_available=False,
        recurrence_rule=recurrence_rule,
        deleted_at=None
    )
    session.add(entry)
    session.flush()
    return entry


def _selftest():
    """Module self-test."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        CalendarEntry.metadata.create_all(engine)
        
        with Session(engine) as session:
            utc = timezone.utc
            
            # Test: Add availability
            start1 = datetime(2024, 1, 15, 9, 0, 0, tzinfo=utc)
            end1 = datetime(2024, 1, 15, 17, 0, 0, tzinfo=utc)
            avail = add_availability(session, resource_id=1, start=start1, end=end1)
            assert avail.id is not None
            assert avail.is_available is True
            assert avail.recurrence_rule is None
            
            # Test: Add unavailability with recurrence rule
            start2 = datetime(2024, 1, 16, 9, 0, 0, tzinfo=utc)
            end2 = datetime(2024, 1, 16, 17, 0, 0, tzinfo=utc)
            unavail = add_unavailability(
                session, resource_id=1, start=start2, end=end2,
                recurrence_rule="FREQ=WEEKLY;BYDAY=MO,WE,FR"
            )
            assert unavail.is_available is False
            assert unavail.recurrence_rule == "FREQ=WEEKLY;BYDAY=MO,WE,FR"
            
            session.commit()
            
            # Test: Query entries
            all_entries = session.query(CalendarEntry).filter_by(resource_id=1).all()
            assert len(all_entries) == 2
            
            # Test: Detect overlapping intervals (exact match)
            try:
                add_availability(session, resource_id=1, start=start1, end=end1)
                assert False, "Expected ConflictError for exact overlap"
            except ConflictError:
                pass
            
            # Test: Detect partial overlap
            try:
                add_availability(
                    session, resource_id=1,
                    start=datetime(2024, 1, 15, 12, 0, 0, tzinfo=utc),
                    end=datetime(2024, 1, 15, 20, 0, 0, tzinfo=utc)
                )
                assert False, "Expected ConflictError for partial overlap"
            except ConflictError:
                pass
            
            # Test: Soft deletion respected in queries
            avail.deleted_at = datetime.now(utc)
            session.commit()
            
            active = session.query(CalendarEntry).filter(
                CalendarEntry.resource_id == 1,
                CalendarEntry.deleted_at.is_(None)
            ).all()
            assert len(active) == 1
            assert active[0].id == unavail.id
            
            # Can add new entry in same slot after soft delete
            avail2 = add_availability(session, resource_id=1, start=start1, end=end1)
            assert avail2.id != avail.id
            
            # Test: Timezone-aware timestamps (using zoneinfo)
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo("America/New_York")
                start3 = datetime(2024, 6, 1, 10, 0, 0, tzinfo=tz)
                end3 = datetime(2024, 6, 1, 18, 0, 0, tzinfo=tz)
                entry_tz = add_availability(session, resource_id=2, start=start3, end=end3)
                assert entry_tz.start == start3
            except ImportError:
                # pytz fallback or skip if no zoneinfo (Python 3.9+ has it)
                pass
            
            # Test: Multiple resource types (different resource_ids)
            res_eq = add_availability(
                session, resource_id=999, start=start1, end=end1
            )
            assert res_eq.resource_id == 999
            
            # Verify no conflict between different resources at same time
            res_eq2 = add_availability(
                session, resource_id=888, start=start1, end=end1
            )
            assert res_eq2.resource_id == 888
            
            session.commit()
        
        engine.dispose()


if __name__ == "__main__":
    _selftest()
