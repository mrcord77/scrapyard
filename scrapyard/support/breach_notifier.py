"""
breach_notifier — Notify stakeholders when an SLA breach occurs, ensuring timely corrective actions. It provides a flexible and extensible mechanism for defining and sending breach notifications through multiple channe

### PART-META-JSON
{
  "name": "breach_notifier",
  "layer": "support",
  "purpose": "Notify stakeholders when an SLA breach occurs, ensuring timely corrective actions. It provides a flexible and extensible mechanism for defining and sending breach notifications through multiple channe",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: get_default_notifier(); notify_breach(breach); create_breach_notification(breach_time, status, channel_id, details, severity); NotificationChannel(...); BreachNotification(...); BreachNotifier(...).",
  "outputs": "Returns: get_default_notifier -> BreachNotifier; notify_breach -> None; create_breach_notification -> BreachNotification.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.breach_notifier`.",
  "example": "from scrapyard.support.breach_notifier import *",
  "import_path": "scrapyard.support.breach_notifier"
}
### END-PART-META
"""
from sqlalchemy import String, DateTime, JSON, ForeignKey, Index, UniqueConstraint, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable
import os, logging, tempfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# PART-META-JSON: {"status": "core", "import_path": "scrapyard.support.breach_notifier", "layer": "support", "module": "breach_notifier", "domain": "sla_management"}

class NotificationChannel(IntPKModel):
    __tablename__ = "notification_channels"
    
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

class BreachNotification(IntPKModel):
    __tablename__ = "breach_notifications"
    
    breach_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(50), server_default='pending')
    channel_id: Mapped[int] = mapped_column(ForeignKey('notification_channels.id'), nullable=False)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    severity: Mapped[str] = mapped_column(String(50), server_default='info')
    
    __table_args__ = (
        Index('idx_breach_notification_channel', 'channel_id'),
        UniqueConstraint('breach_time', 'status'),
    )

class BreachNotifier:
    def __init__(self):
        self.channels: Dict[int, NotificationChannel] = {}
        self._handlers: Dict[str, Callable[[Dict[str, Any]], None]] = {
            'email': self._send_email,
            'webhook': self._send_webhook,
            'sms': self._send_sms,
        }

    def add_channel(self, channel: NotificationChannel) -> None:
        self.channels[channel.id] = channel

    def notify_breach(self, breach: BreachNotification) -> None:
        if not breach.channel_id or breach.channel_id not in self.channels:
            logger.warning('No valid channel for breach notification')
            return

        channel = self.channels[breach.channel_id]
        handler = self._handlers.get(channel.type)
        if handler:
            handler(breach.details)
        else:
            logger.warning(f'Unknown channel type: {channel.type}')

    def _send_email(self, details: Dict[str, Any]) -> None:
        logger.info('Sending email notification')

    def _send_webhook(self, details: Dict[str, Any]) -> None:
        logger.info('Sending webhook notification')

    def _send_sms(self, details: Dict[str, Any]) -> None:
        logger.info('Sending SMS notification')

_default_notifier: Optional[BreachNotifier] = None

def get_default_notifier() -> BreachNotifier:
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = BreachNotifier()
    return _default_notifier

def notify_breach(breach: BreachNotification) -> None:
    """Notify stakeholders of a breach using the default notifier."""
    notifier = get_default_notifier()
    notifier.notify_breach(breach)

def create_breach_notification(breach_time: datetime, status: str, channel_id: int, details: Dict[str, Any], severity: str) -> BreachNotification:
    return BreachNotification(
        breach_time=breach_time,
        status=status,
        channel_id=channel_id,
        details=details,
        severity=severity
    )

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, 'test.db')
        engine = create_engine(f'sqlite:///{db_path}')
        
        IntPKModel.metadata.create_all(engine)
        
        session = Session(engine)
        try:
            email_channel = NotificationChannel(name='email', type='email', config={'from': 'admin@example.com'})
            webhook_channel = NotificationChannel(name='webhook', type='webhook', config={'url': 'http://example.com/webhook'})
            sms_channel = NotificationChannel(name='sms', type='sms', config={'phone_number': '+1234567890'})

            session.add(email_channel)
            session.add(webhook_channel)
            session.add(sms_channel)
            session.commit()

            breach_details = {'service': 'database', 'severity': 2}
            breach_notification = create_breach_notification(
                datetime.now(timezone.utc), 
                'pending', 
                email_channel.id, 
                breach_details, 
                'info'
            )
            session.add(breach_notification)
            session.commit()

            notifier = BreachNotifier()
            notifier.add_channel(email_channel)
            notifier.notify_breach(breach_notification)

            stmt = select(BreachNotification).where(BreachNotification.id == breach_notification.id)
            result = session.execute(stmt).scalar_one_or_none()
            
            assert result is not None, 'Breach notification not found in database'
            assert result.status == 'pending', f'Breach notification status incorrect: {result.status}'
            assert result.severity == 'info', f'Breach notification severity incorrect: {result.severity}'

            assert len(notifier.channels) == 1, 'Incorrect number of channels in notifier'
            assert isinstance(notifier.channels[email_channel.id], NotificationChannel), 'Channel not added to notifier correctly'

            stmt_channels = select(NotificationChannel)
            all_channels = session.execute(stmt_channels).scalars().all()
            assert len(all_channels) == 3, f'Expected 3 channels, got {len(all_channels)}'
            
            get_default_notifier().add_channel(email_channel)
            notify_breach(breach_notification)
            
        finally:
            session.close()
            engine.dispose()
            
    logger.info('Selftest passed')

if __name__ == '__main__':
    _selftest()
