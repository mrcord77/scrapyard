"""
slot_manager — Manages creation, allocation, and modification of bookable time slots for meeting scheduling. Provides a reusable, type-safe, and scalable interface for time slot lifecycle management.

### PART-META-JSON
{
  "name": "slot_manager",
  "layer": "scheduling",
  "purpose": "Manages creation, allocation, and modification of bookable time slots for meeting scheduling. CANONICAL OWNER of the scheduling Slot model (table slot_manager_slots): buffer_calculator, no_show_tracker, slot_replacer and slot_searcher import Slot from here instead of defining duplicates.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model"],
  "inputs": "SQLAlchemy Session plus slot fields (start/end datetimes, resource_id, status).",
  "outputs": "Slot and SlotAllocation ORM instances; ValueError on overlap or double allocation.",
  "files_created": [],
  "security_notes": "No authentication or authorization is performed here: callers must verify the acting user may create/allocate slots for the given resource before calling. Overlap and double-allocation checks are read-then-write (not atomic under concurrent sessions); wrap calls in a transaction with appropriate isolation or a unique constraint for multi-writer deployments.",
  "ai_usage": "Import what you need from `scrapyard.scheduling.slot_manager`.",
  "example": "from scrapyard.scheduling.slot_manager import *",
  "import_path": "scrapyard.scheduling.slot_manager"
}
### END-PART-META
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Integer, String, ForeignKey, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker, synonym
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class Slot(IntPKModel):
    """Canonical scheduling slot model.

    slot_manager is the canonical owner of this table. Other scheduling
    parts (buffer_calculator, no_show_tracker, slot_replacer, slot_searcher)
    import this model instead of declaring their own copies.
    ``start_time``/``end_time`` are synonyms for ``start``/``end`` so both
    naming conventions used across the layer keep working.
    """

    __tablename__ = "slot_manager_slots"

    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, default=0)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="available")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    start_time = synonym("start")
    end_time = synonym("end")


class SlotAllocation(IntPKModel):
    __tablename__ = "slot_allocations"
    
    slot_id: Mapped[int] = mapped_column(ForeignKey("slot_manager_slots.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    allocated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def create_slot(session: Session, start: datetime, end: datetime, resource_id: int) -> Slot:
    """Create a new time slot for a resource, preventing overlaps."""
    if start >= end:
        raise ValueError("Start time must be before end time")
    
    overlap_check = select(Slot).where(
        Slot.resource_id == resource_id,
        Slot.start < end,
        Slot.end > start
    )
    
    existing = session.execute(overlap_check).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"Overlapping slot exists for resource {resource_id}")
    
    slot = Slot(start=start, end=end, resource_id=resource_id)
    session.add(slot)
    session.flush()
    logger.info(f"Created slot {slot.id} for resource {resource_id}")
    return slot


def allocate_slot(session: Session, slot_id: int, user_id: int) -> SlotAllocation:
    """Allocate an existing slot to a user atomically."""
    slot = session.get(Slot, slot_id)
    if slot is None:
        raise ValueError(f"Slot {slot_id} does not exist")
    
    existing_alloc = session.execute(
        select(SlotAllocation).where(SlotAllocation.slot_id == slot_id)
    ).scalar_one_or_none()
    if existing_alloc is not None:
        raise ValueError(f"Slot {slot_id} is already allocated")
    
    allocation = SlotAllocation(slot_id=slot_id, user_id=user_id, allocated_at=datetime.utcnow())
    session.add(allocation)
    session.flush()
    logger.info(f"Allocated slot {slot_id} to user {user_id}")
    return allocation


def _selftest():
    import tempfile
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        IntPKModel.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        try:
            now = datetime.now(timezone.utc)
            
            # Test valid slot creation
            slot1 = create_slot(session, now, now + timedelta(hours=1), 1)
            assert slot1.id is not None
            assert slot1.resource_id == 1
            assert isinstance(slot1, IntPKModel)
            
            # Test allocation
            alloc1 = allocate_slot(session, slot1.id, 100)
            assert alloc1.id is not None
            assert alloc1.slot_id == slot1.id
            assert alloc1.user_id == 100
            assert isinstance(alloc1, IntPKModel)
            
            # Test overlapping slot rejection for same resource
            try:
                create_slot(session, now + timedelta(minutes=30), now + timedelta(hours=1, minutes=30), 1)
                assert False, "Expected ValueError for overlapping slot"
            except ValueError:
                pass
            
            # Test non-overlapping slot for different resource succeeds
            slot2 = create_slot(session, now, now + timedelta(hours=1), 2)
            assert slot2.id is not None
            
            # Test allocation for non-existent slot
            try:
                allocate_slot(session, 99999, 100)
                assert False, "Expected ValueError for non-existent slot"
            except ValueError:
                pass
            
            # Test retrieval
            retrieved_slot = session.get(Slot, slot1.id)
            assert retrieved_slot is not None
            assert retrieved_slot.id == slot1.id
            
            retrieved_alloc = session.get(SlotAllocation, alloc1.id)
            assert retrieved_alloc is not None
            assert retrieved_alloc.user_id == 100
            
            session.commit()

            # Canonical-owner contract: synonyms keep both naming styles working.
            assert slot1.start_time == slot1.start
            assert slot1.end_time == slot1.end
            assert slot1.status == "available"

            logger.info("Selftest completed successfully")
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
