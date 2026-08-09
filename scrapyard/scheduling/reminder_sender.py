"""
reminder_sender — reminder sender

### PART-META-JSON
{
  "name": "reminder_sender",
  "layer": "scheduling",
  "purpose": "reminder sender",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: send_reminder(slot, minutes_before); schedule_reminder(slot); Slot(...); Reminder(...).",
  "outputs": "Returns: send_reminder -> None; schedule_reminder -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.scheduling.reminder_sender`.",
  "example": "from scrapyard.scheduling.reminder_sender import *",
  "import_path": "scrapyard.scheduling.reminder_sender"
}
### END-PART-META
"""

from sqlalchemy import create_engine, String, DateTime, func, select, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional
import os, logging, tempfile

logger = logging.getLogger(__name__)

# Define Slot model for type validation
@dataclass
class Slot:
    id: int
    time: datetime

class Reminder(IntPKModel):
    __tablename__ = 'reminders'
    
    slot_id: Mapped[int] = mapped_column(nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default='pending', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

Index('idx_reminders_slot_id_scheduled_for', Reminder.slot_id, Reminder.scheduled_for)
UniqueConstraint(Reminder.slot_id, Reminder.scheduled_for, name='uq_reminders_slot_id_scheduled_for')

# Session factory - configured in _selftest
Session_factory = sessionmaker()

def send_reminder(slot: Slot, minutes_before: int) -> None:
    """Sends a reminder for the given slot."""
    scheduled_time = slot.time - timedelta(minutes=minutes_before)
    now = datetime.now(timezone.utc)
    
    with Session_factory() as session:
        existing_reminder = session.execute(
            select(Reminder).where(
                Reminder.slot_id == slot.id,
                Reminder.scheduled_for == scheduled_time
            )
        ).scalar_one_or_none()
        
        if not existing_reminder:
            reminder = Reminder(
                slot_id=slot.id, 
                scheduled_for=scheduled_time,
                status='sent',
                sent_at=now
            )
            session.add(reminder)
            session.commit()
            logger.info(f"Reminder for slot {slot.id} at {scheduled_time} sent.")
        else:
            if existing_reminder.status != 'sent':
                existing_reminder.status = 'sent'
                existing_reminder.sent_at = now
                session.commit()
                logger.info(f"Reminder for slot {slot.id} at {scheduled_time} sent.")
            else:
                logger.info(f"Reminder for slot {slot.id} already exists and will not be duplicated.")

def schedule_reminder(slot: Slot) -> None:
    """Schedules a reminder for the given slot."""
    send_reminder(slot, 15)

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        
        # Initialize database
        engine = create_engine(f"sqlite:///{db_path}")
        Session_factory.configure(bind=engine)
        IntPKModel.metadata.create_all(engine)
        
        # Create a sample slot
        sample_slot = Slot(id=1, time=datetime(2023, 10, 1, 12, 0, tzinfo=timezone.utc))
        
        # Test sending reminder
        send_reminder(sample_slot, 15)
        with Session_factory() as session:
            reminder = session.execute(
                select(Reminder).where(
                    Reminder.slot_id == sample_slot.id,
                    Reminder.scheduled_for == (sample_slot.time - timedelta(minutes=15))
                )
            ).scalar_one()
            
            assert reminder.status == 'sent'
            assert reminder.sent_at is not None
        
        # Test sending duplicate reminder
        send_reminder(sample_slot, 15)
        with Session_factory() as session:
            reminders = session.execute(
                select(Reminder).where(
                    Reminder.slot_id == sample_slot.id,
                    Reminder.scheduled_for == (sample_slot.time - timedelta(minutes=15))
                )
            ).scalars().all()
            
            assert len(reminders) == 1
        
        # Test scheduling reminder with a new slot
        sample_slot2 = Slot(id=2, time=datetime(2023, 10, 1, 14, 0, tzinfo=timezone.utc))
        schedule_reminder(sample_slot2)
        with Session_factory() as session:
            reminder = session.execute(
                select(Reminder).where(
                    Reminder.slot_id == sample_slot2.id,
                    Reminder.scheduled_for == (sample_slot2.time - timedelta(minutes=15))
                )
            ).scalar_one()
            
            assert reminder.status == 'sent'
        
        engine.dispose()

if __name__ == "__main__":
    _selftest()
