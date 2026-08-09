"""
notification - Send typed, status-tracked notifications to approvers and stakeholders during approvals.

### PART-META-JSON
{
  "name": "notification",
  "layer": "approvals_workfl",
  "purpose": "Send typed, status-tracked notifications to approvers and stakeholders during approvals.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure(engine); send_notification(notification).",
  "outputs": "Notification rows with NotificationType/NotificationStatus plus NotificationLog entries.",
  "files_created": [],
  "security_notes": "Delivery is a log-only placeholder offline (no network). Recipient addresses are PII - avoid info-level logging in production. Status transitions and logs give an audit trail of who was told what, when; when wiring real channels, rate-limit to avoid notification storms.",
  "ai_usage": "Import what you need from `scrapyard.approvals_workfl.notification`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.approvals_workfl.notification import configure",
  "import_path": "scrapyard.approvals_workfl.notification"
}
### END-PART-META
"""
from enum import Enum
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import logging

from sqlalchemy import (
    String,
    DateTime,
    JSON,
    func,
    select,
    ForeignKey,
    Enum as SQLEnum,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship

from scrapyard.database.base_model import IntPKModel


logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    EMAIL = "email"
    IN_APP = "in_app"
    SMS = "sms"
    PUSH = "push"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DELIVERED = "delivered"


class Notification(IntPKModel):
    __tablename__ = "notification_notifications"

    type: Mapped[NotificationType] = mapped_column(
        SQLEnum(NotificationType, create_constraint=False, native_enum=False),
        nullable=False,
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[NotificationStatus] = mapped_column(
        SQLEnum(NotificationStatus, create_constraint=False, native_enum=False),
        nullable=False,
        default=NotificationStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    logs: Mapped[List["NotificationLog"]] = relationship(
        "NotificationLog",
        back_populates="notification",
        cascade="all, delete-orphan",
    )


class NotificationLog(IntPKModel):
    __tablename__ = "notification_logs"

    notification_id: Mapped[int] = mapped_column(
        ForeignKey("notification_notifications.id"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    notification: Mapped["Notification"] = relationship(
        "Notification", back_populates="logs"
    )


_engine: Optional[Engine] = None


def configure(engine: Optional[Engine]) -> None:
    """Bind an engine for this module's DB operations."""
    global _engine
    _engine = engine


def _get_session() -> Session:
    if _engine is None:
        raise RuntimeError("No engine configured for notifications")
    return Session(_engine)


def send_notification(notification: Notification) -> None:
    """Persist a notification and record a sent log entry."""
    if not isinstance(notification, Notification):
        raise TypeError(
            f"send_notification expects Notification, got {type(notification).__name__}"
        )

    session = _get_session()
    try:
        notification.status = NotificationStatus.SENT
        notification.updated_at = datetime.now(timezone.utc)
        session.add(notification)
        session.flush()

        log = NotificationLog(
            notification_id=notification.id,
            event="sent",
            details={"type": notification.type.value, "payload": notification.payload},
        )
        session.add(log)
        session.commit()
        logger.info("Sent notification id=%s type=%s", notification.id, notification.type.value)
    except Exception:
        session.rollback()
        raise


def get_notification_status(notification_id: int) -> NotificationStatus:
    """Return the current status of a notification by id."""
    session = _get_session()
    notification = session.get(Notification, notification_id)
    if notification is None:
        raise ValueError(f"Notification {notification_id} not found")
    return notification.status


def _selftest() -> None:
    import os
    import tempfile

    from sqlalchemy import create_engine

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_notifications.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        configure(engine)

        try:
            Notification.metadata.create_all(engine)

            notification = Notification(
                type=NotificationType.EMAIL,
                payload={"to": "approver@example.com", "subject": "Approval Required"},
            )
            send_notification(notification)

            assert notification.id is not None
            assert notification.status == NotificationStatus.SENT

            session = Session(engine)
            try:
                log = session.execute(
                    select(NotificationLog).where(
                        NotificationLog.notification_id == notification.id
                    )
                ).scalar_one()
                assert log.event == "sent"
                assert log.notification_id == notification.id
            finally:
                session.close()

            status = get_notification_status(notification.id)
            assert status == NotificationStatus.SENT
            assert isinstance(status, NotificationStatus)
        finally:
            configure(None)
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("notification selftest OK")
