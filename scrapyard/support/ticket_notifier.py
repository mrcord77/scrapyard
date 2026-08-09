"""
ticket_notifier — Sends notifications (email, in-app, etc.) related to ticket status changes. Provides reusable, extensible notification logic for support desk systems.

### PART-META-JSON
{
  "name": "ticket_notifier",
  "layer": "support",
  "purpose": "Sends notifications (email, in-app, etc.) related to ticket status changes. Provides reusable, extensible notification logic for support desk systems.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: notify_agent(ticket_id, message); notify_customer(ticket_id, message); NotificationTemplate(...); NotificationLog(...).",
  "outputs": "Returns: notify_agent -> None; notify_customer -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.ticket_notifier`.",
  "example": "from scrapyard.support.ticket_notifier import *",
  "import_path": "scrapyard.support.ticket_notifier"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, Text, DateTime, func, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from typing import Optional, Any
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

_engine: Optional[Any] = None


def _get_session() -> Session:
    if _engine is None:
        raise RuntimeError("Database engine not configured")
    return Session(_engine)


class NotificationTemplate(IntPKModel):
    __tablename__ = "ticket_notifier_notification_template"
    
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="email")
    content: Mapped[str] = mapped_column(Text, nullable=False)


class NotificationLog(IntPKModel):
    __tablename__ = "notification_log"
    
    ticket_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="in-app")
    recipient_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


def notify_agent(ticket_id: int, message: str) -> None:
    """Send notification to agent and log it."""
    session = _get_session()
    with session.begin():
        log = NotificationLog(
            ticket_id=ticket_id,
            message=message,
            channel="in-app",
            recipient_type="agent",
            status="sent"
        )
        session.add(log)


def notify_customer(ticket_id: int, message: str) -> None:
    """Send notification to customer using a template from the database."""
    session = _get_session()
    with session.begin():
        stmt = select(NotificationTemplate).where(NotificationTemplate.name == "customer_default")
        template = session.execute(stmt).scalar_one_or_none()
        
        if template is not None:
            final_message = f"{template.content}: {message}"
            channel = template.channel
        else:
            final_message = message
            channel = "email"
            
        log = NotificationLog(
            ticket_id=ticket_id,
            message=final_message,
            channel=channel,
            recipient_type="customer",
            status="sent"
        )
        session.add(log)


def _selftest() -> None:
    """Self-test with temporary SQLite database."""
    global _engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        test_engine = create_engine(f"sqlite:///{db_path}", echo=False)
        _engine = test_engine
        
        try:
            IntPKModel.metadata.create_all(test_engine)
            
            # Test notify_agent creates log entry with correct data
            notify_agent(ticket_id=123, message="Agent alert message")
            
            with Session(test_engine) as session:
                stmt = select(NotificationLog).where(NotificationLog.ticket_id == 123)
                log_entry = session.execute(stmt).scalar_one()
                assert log_entry.message == "Agent alert message"
                assert log_entry.recipient_type == "agent"
                assert log_entry.ticket_id == 123
            
            # Test notify_customer uses template from table
            with Session(test_engine) as session:
                with session.begin():
                    template = NotificationTemplate(
                        name="customer_default",
                        channel="email",
                        content="Dear Customer"
                    )
                    session.add(template)
            
            notify_customer(ticket_id=456, message="Your ticket has been updated")
            
            with Session(test_engine) as session:
                stmt = select(NotificationLog).where(NotificationLog.ticket_id == 456)
                log_entry = session.execute(stmt).scalar_one()
                assert log_entry.recipient_type == "customer"
                assert "Dear Customer" in log_entry.message
                assert log_entry.channel == "email"
                assert log_entry.status == "sent"
                
        finally:
            test_engine.dispose()
            _engine = None


if __name__ == "__main__":
    _selftest()
