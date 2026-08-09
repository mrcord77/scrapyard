"""
scheduling_event — Track and manage scheduled events and their impact on resource availability. Provides a reusable foundation for resource scheduling systems.

### PART-META-JSON
{
  "name": "scheduling_event",
  "layer": "projects",
  "purpose": "Track and manage scheduled events and their impact on resource availability. Provides a reusable foundation for resource scheduling systems.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: validate_event_times(start, end, allow_past_start); ensure_tz_aware(dt); create_event(session, start, end, resource_id, status, recurrence_rule, title, description); update_event(session, event_id, **kwargs); get_event(session, event_id); EventStatus(...); SchedulingEvent(...) (plus more).",
  "outputs": "Returns: validate_event_times -> None; ensure_tz_aware -> datetime; create_event -> SchedulingEvent; update_event -> SchedulingEvent; get_event -> Optional[SchedulingEvent].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.scheduling_event`.",
  "example": "from scrapyard.projects.scheduling_event import *",
  "import_path": "scrapyard.projects.scheduling_event"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, select, create_engine, Table, Column as SAColumn
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class EventStatus:
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SchedulingEvent(IntPKModel):
    __tablename__ = "scheduling_events"
    
    start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    resource_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("resources.id"), 
        nullable=False, 
        index=True
    )
    status: Mapped[str] = mapped_column(String(50), default=EventStatus.SCHEDULED)
    recurrence_rule: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    
    def __repr__(self) -> str:
        return f"<SchedulingEvent(id={self.id}, resource_id={self.resource_id}, start={self.start}, end={self.end})>"


def validate_event_times(start: datetime, end: datetime, allow_past_start: bool = False) -> None:
    """Validate event start and end times."""
    if start >= end:
        raise ValueError("Start time must be before end time")
    
    if not allow_past_start:
        now = datetime.now(timezone.utc)
        if start < now:
            raise ValueError("Start time cannot be in the past")


def ensure_tz_aware(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def create_event(
    session: Session,
    start: datetime,
    end: datetime,
    resource_id: int,
    status: str = EventStatus.SCHEDULED,
    recurrence_rule: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None
) -> SchedulingEvent:
    """Create a new scheduling event."""
    start = ensure_tz_aware(start)
    end = ensure_tz_aware(end)
    
    validate_event_times(start, end, allow_past_start=False)
    
    event = SchedulingEvent(
        start=start,
        end=end,
        resource_id=resource_id,
        status=status,
        recurrence_rule=recurrence_rule,
        title=title,
        description=description
    )
    session.add(event)
    session.flush()
    return event


def update_event(session: Session, event_id: int, **kwargs) -> SchedulingEvent:
    """Update an existing scheduling event."""
    event = session.get(SchedulingEvent, event_id)
    if event is None:
        raise ValueError(f"Event with id {event_id} not found")
    
    new_start = kwargs.get('start', event.start)
    new_end = kwargs.get('end', event.end)
    
    if 'start' in kwargs or 'end' in kwargs:
        new_start = ensure_tz_aware(new_start)
        new_end = ensure_tz_aware(new_end)
        validate_event_times(new_start, new_end, allow_past_start=True)
        event.start = new_start
        event.end = new_end
    
    for key in ['status', 'recurrence_rule', 'title', 'description', 'resource_id']:
        if key in kwargs:
            setattr(event, key, kwargs[key])
    
    session.flush()
    return event


def get_event(session: Session, event_id: int) -> Optional[SchedulingEvent]:
    """Retrieve an event by ID."""
    return session.get(SchedulingEvent, event_id)


def list_events(
    session: Session,
    resource_id: Optional[int] = None,
    status: Optional[str] = None,
    start_after: Optional[datetime] = None,
    start_before: Optional[datetime] = None
) -> List[SchedulingEvent]:
    """Query events with optional filters."""
    stmt = select(SchedulingEvent)
    
    if resource_id is not None:
        stmt = stmt.where(SchedulingEvent.resource_id == resource_id)
    if status is not None:
        stmt = stmt.where(SchedulingEvent.status == status)
    if start_after is not None:
        stmt = stmt.where(SchedulingEvent.start >= start_after)
    if start_before is not None:
        stmt = stmt.where(SchedulingEvent.start <= start_before)
    
    stmt = stmt.order_by(SchedulingEvent.start)
    return list(session.scalars(stmt))


def parse_recurrence_rule(rule: Optional[str]) -> Dict[str, Any]:
    """Parse a recurrence rule string (RRULE format) into a dictionary."""
    result: Dict[str, Any] = {}
    if not rule:
        return result
    
    parts = rule.split(';')
    for part in parts:
        if '=' in part:
            key, value = part.split('=', 1)
            result[key.strip()] = value.strip()
    return result


def _selftest() -> None:
    """Run self-contained tests using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        resources_table = Table(
            'resources', 
            IntPKModel.metadata, 
            SAColumn('id', Integer, primary_key=True)
        )
        
        IntPKModel.metadata.create_all(engine)
        
        with Session(engine) as session:
            now = datetime.now(timezone.utc)
            
            event = create_event(
                session=session,
                start=now + timedelta(hours=1),
                end=now + timedelta(hours=2),
                resource_id=1,
                title="Test Event",
                description="Test Description",
                recurrence_rule="FREQ=DAILY;INTERVAL=1"
            )
            session.commit()
            
            retrieved = get_event(session, event.id)
            assert retrieved is not None
            assert retrieved.id == event.id
            assert retrieved.resource_id == 1
            assert retrieved.title == "Test Event"
            assert retrieved.recurrence_rule == "FREQ=DAILY;INTERVAL=1"
            logger.info("Test 1 PASSED: Create and retrieve")
            
            updated = update_event(
                session=session,
                event_id=event.id,
                title="Updated Title",
                status=EventStatus.IN_PROGRESS
            )
            session.commit()
            
            assert updated.title == "Updated Title"
            assert updated.status == EventStatus.IN_PROGRESS
            
            retrieved2 = get_event(session, event.id)
            assert retrieved2.title == "Updated Title"
            logger.info("Test 2 PASSED: Update and verify")
            
            try:
                create_event(
                    session=session,
                    start=now - timedelta(hours=2),
                    end=now - timedelta(hours=1),
                    resource_id=1
                )
                assert False, "Should have raised ValueError for past start time"
            except ValueError as e:
                assert "past" in str(e).lower()
                logger.info("Test 3 PASSED: Past start time validation")
            
            for i in range(3):
                create_event(
                    session=session,
                    start=now + timedelta(days=i+2),
                    end=now + timedelta(days=i+2, hours=1),
                    resource_id=2,
                    status=EventStatus.SCHEDULED
                )
            session.commit()
            
            resource_events = list_events(session, resource_id=2)
            assert len(resource_events) == 3
            
            scheduled_events = list_events(session, status=EventStatus.SCHEDULED)
            assert len(scheduled_events) >= 3
            
            future_events = list_events(session, start_after=now + timedelta(days=3))
            assert len(future_events) >= 2
            
            logger.info("Test 4 PASSED: Query with filters")
            
            rule_str = "FREQ=WEEKLY;BYDAY=MO,WE,FR;INTERVAL=2"
            parsed = parse_recurrence_rule(rule_str)
            assert parsed["FREQ"] == "WEEKLY"
            assert parsed["BYDAY"] == "MO,WE,FR"
            assert parsed["INTERVAL"] == "2"
            
            empty_parsed = parse_recurrence_rule("")
            assert empty_parsed == {}
            
            none_parsed = parse_recurrence_rule(None)
            assert none_parsed == {}
            
            logger.info("Test 5 PASSED: Recurrence rule parsing")
            
        engine.dispose()
        logger.info("All selftests PASSED")


if __name__ == "__main__":
    _selftest()
