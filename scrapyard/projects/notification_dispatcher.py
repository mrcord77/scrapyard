"""
notification_dispatcher — Sends timely notifications for project events, ensuring users stay informed about task status, deadlines, and project changes. It provides a flexible and scalable mechanism for managing and delivering

### PART-META-JSON
{
  "name": "notification_dispatcher",
  "layer": "projects",
  "purpose": "Sends timely notifications for project events, ensuring users stay informed about task status, deadlines, and project changes. It provides a flexible and scalable mechanism for managing and delivering",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure(engine); send_notification(user_id, event_type, payload); schedule_reminder(user_id, event_time, message); get_notifications_by_user(user_id); Notification(...); NotificationSchedule(...).",
  "outputs": "Returns: configure -> None; send_notification -> None; schedule_reminder -> None; get_notifications_by_user -> list[Notification].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.notification_dispatcher`.",
  "example": "from scrapyard.projects.notification_dispatcher import *",
  "import_path": "scrapyard.projects.notification_dispatcher"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, JSON, ForeignKey, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
import tempfile
import logging
import time

logger = logging.getLogger(__name__)

_engine = None
_Session = None


def configure(engine) -> None:
    """Configure the module with a SQLAlchemy engine."""
    global _engine, _Session
    _engine = engine
    _Session = sessionmaker(bind=engine, expire_on_commit=False)


class Notification(IntPKModel):
    __tablename__ = "notification_dispatcher_notifications"
    
    user_id: Mapped[int] = mapped_column(ForeignKey("notification_dispatcher_users.id"))
    event_type: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class NotificationSchedule(IntPKModel):
    __tablename__ = "notification_schedules"
    
    user_id: Mapped[int] = mapped_column(ForeignKey("notification_dispatcher_users.id"))
    scheduled_for: Mapped[datetime]
    message: Mapped[str]
    sent: Mapped[bool] = mapped_column(default=False)


def send_notification(user_id: int, event_type: str, payload: dict) -> None:
    """Send a notification to a user."""
    if _Session is None:
        raise RuntimeError("notification_dispatcher not configured")
    
    with _Session() as session:
        notification = Notification(
            user_id=user_id,
            event_type=event_type,
            payload=payload
        )
        session.add(notification)
        session.commit()
        logger.info(f"Notification sent to user {user_id}: {event_type}")


def schedule_reminder(user_id: int, event_time: datetime, message: str) -> None:
    """Schedule a reminder for a future time."""
    if _Session is None:
        raise RuntimeError("notification_dispatcher not configured")
    
    with _Session() as session:
        schedule = NotificationSchedule(
            user_id=user_id,
            scheduled_for=event_time,
            message=message,
            sent=False
        )
        session.add(schedule)
        session.commit()
        logger.info(f"Reminder scheduled for user {user_id} at {event_time}")


def get_notifications_by_user(user_id: int) -> list[Notification]:
    """Get all notifications for a specific user."""
    if _Session is None:
        raise RuntimeError("notification_dispatcher not configured")
    
    with _Session() as session:
        stmt = select(Notification).where(Notification.user_id == user_id)
        return list(session.scalars(stmt).all())


def _selftest() -> bool:
    """Offline selftest using temporary SQLite database."""
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = f"{tmpdir}/test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        
        # Define a minimal User model for FK constraint
        class _User(IntPKModel):
            __tablename__ = "notification_dispatcher_users"
            username: Mapped[str] = mapped_column(String(50))
        
        # Create all tables
        IntPKModel.metadata.create_all(engine)
        configure(engine)
        
        # Test: send_notification creates record
        send_notification(1, "task_created", {"task_id": 101, "title": "Test Task"})
        
        with Session(engine) as session:
            count = session.query(Notification).filter_by(user_id=1).count()
            assert count == 1, f"Expected 1 notification, got {count}"
        
        # Test: schedule_reminder adds entry
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        schedule_reminder(1, future, "Task deadline reminder")
        
        with Session(engine) as session:
            count = session.query(NotificationSchedule).filter_by(user_id=1).count()
            assert count == 1, f"Expected 1 schedule, got {count}"
        
        # Test: get_notifications_by_user returns correct data
        notifs = get_notifications_by_user(1)
        assert len(notifs) == 1
        assert notifs[0].event_type == "task_created"
        assert notifs[0].payload == {"task_id": 101, "title": "Test Task"}
        
        # Test: multiple notifications for same user
        send_notification(1, "task_updated", {"task_id": 102})
        notifs = get_notifications_by_user(1)
        assert len(notifs) == 2
        
        # Test: different user isolation
        send_notification(2, "task_created", {"task_id": 201})
        notifs_user2 = get_notifications_by_user(2)
        assert len(notifs_user2) == 1
        assert notifs_user2[0].user_id == 2
        
        # Verify timing constraint
        elapsed = time.time() - start_time
        assert elapsed < 20, f"Selftest took {elapsed}s, exceeds 20s limit"
    
    return True


if __name__ == "__main__":
    _selftest()
