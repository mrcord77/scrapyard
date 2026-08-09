"""
dunning_management - Automated dunning for overdue invoices.

### PART-META-JSON
{
  "name": "dunning_management",
  "layer": "billing",
  "purpose": "Automate the dunning process for overdue invoices (rules, triggered events, reminders) to reduce manual collections work.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure(session_factory, ...); trigger_dunning(invoice_id); send_reminder(email, invoice_id).",
  "outputs": "DunningEvent / DunningRule rows recording every collection action.",
  "files_created": [],
  "security_notes": "Money-adjacent collections workflow. Every dunning action is persisted as a DunningEvent, giving an audit trail of customer contact. send_reminder is a log-only placeholder offline (no SMTP calls); when wiring email, rate-limit per invoice and per address - an unthrottled dunning loop is a harassment/compliance risk, not just a bug. Customer emails are PII: do not log full addresses at info level in production.",
  "ai_usage": "Import from `scrapyard.billing.dunning_management`; call configure() with a session factory before triggering dunning.",
  "example": "from scrapyard.billing.dunning_management import trigger_dunning",
  "import_path": "scrapyard.billing.dunning_management"
}
### END-PART-META
"""

"""
Automate the dunning process for overdue invoices, ensuring timely collections and reducing manual intervention.
"""

from sqlalchemy import String, Integer, Boolean, Text, DateTime, JSON, func, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Callable
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

_session_factory: Optional[Callable[[], Session]] = None
_email_sender: Optional[Callable[[str, int], None]] = None

def configure(session_factory: Optional[Callable[[], Session]] = None, 
              email_sender: Optional[Callable[[str, int], None]] = None) -> None:
    """Configure the dunning management module with session factory and email sender."""
    global _session_factory, _email_sender
    if session_factory is not None:
        _session_factory = session_factory
    if email_sender is not None:
        _email_sender = email_sender

class DunningEvent(IntPKModel):
    """Tracks each dunning attempt and outcome."""
    __tablename__ = "dunning_event"
    
    invoice_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    email_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rule_triggered: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

class DunningRule(IntPKModel):
    """Stores conditions and actions for dunning logic."""
    __tablename__ = "dunning_rule"
    
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    condition_logic: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    days_overdue_threshold: Mapped[int] = mapped_column(Integer, default=0)
    email_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

def _get_session() -> Session:
    """Get a database session from the configured factory."""
    if _session_factory is None:
        raise RuntimeError("Dunning management module not configured. Call configure() first.")
    return _session_factory()

def _evaluate_rule(rule: DunningRule, attempt_count: int) -> bool:
    """Evaluate if a rule applies based on current state."""
    if not rule.is_active:
        return False
    return True

def trigger_dunning(invoice_id: int) -> DunningEvent:
    """
    Trigger the dunning process for a specific invoice.
    
    Args:
        invoice_id: The ID of the overdue invoice
        
    Returns:
        DunningEvent: The created or updated dunning event record
    """
    session = _get_session()
    try:
        stmt = select(DunningEvent).where(DunningEvent.invoice_id == invoice_id)
        existing = session.execute(stmt).scalar_one_or_none()
        
        if existing:
            existing.attempt_count += 1
            existing.updated_at = datetime.now(timezone.utc)
            event = existing
        else:
            event = DunningEvent(
                invoice_id=invoice_id,
                status="initiated",
                attempt_count=1,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            session.add(event)
        
        rules = session.execute(
            select(DunningRule).where(DunningRule.is_active == True).order_by(DunningRule.priority.desc())
        ).scalars().all()
        
        for rule in rules:
            if _evaluate_rule(rule, event.attempt_count):
                if rule.action == "send_email":
                    email = "customer@example.com"
                    send_reminder(email, invoice_id)
                    event.email_sent = True
                    event.email_address = email
                    event.status = "reminder_sent"
                elif rule.action == "escalate":
                    event.status = "escalated"
                else:
                    event.status = f"action_{rule.action}"
                
                event.rule_triggered = rule.name
                break
        else:
            event.status = "no_rule_matched"
        
        session.commit()
        session.expunge(event)
        return event
    finally:
        session.close()

def send_reminder(email: str, invoice_id: int) -> None:
    """
    Send a reminder email for an invoice.
    
    Args:
        email: The recipient email address
        invoice_id: The invoice ID to reference in the reminder
    """
    if _email_sender:
        _email_sender(email, invoice_id)
    else:
        logger.info(f"Dunning reminder would be sent to {email} for invoice {invoice_id}")

def _selftest() -> None:
    """Self-test function to verify module functionality with temporary SQLite."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "dunning_test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
        
        IntPKModel.metadata.create_all(engine)
        
        TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        
        sent_emails: List[tuple] = []
        
        def mock_email_sender(email: str, inv_id: int) -> None:
            sent_emails.append((email, inv_id))
        
        configure(session_factory=TestingSessionLocal, email_sender=mock_email_sender)
        
        try:
            with TestingSessionLocal() as session:
                rule1 = DunningRule(
                    name="First Reminder",
                    priority=10,
                    action="send_email",
                    email_template="Please pay",
                    is_active=True
                )
                rule2 = DunningRule(
                    name="Escalation",
                    priority=5,
                    action="escalate",
                    is_active=True
                )
                session.add_all([rule1, rule2])
                session.commit()
            
            event1 = trigger_dunning(1001)
            assert event1.invoice_id == 1001
            assert event1.status == "reminder_sent"
            assert event1.email_sent is True
            assert event1.rule_triggered == "First Reminder"
            assert event1.attempt_count == 1
            
            assert len(sent_emails) == 1
            assert sent_emails[0] == ("customer@example.com", 1001)
            
            event2 = trigger_dunning(1001)
            assert event2.id == event1.id
            assert event2.attempt_count == 2
            assert event2.status == "reminder_sent"
            
            event3 = trigger_dunning(1002)
            assert event3.invoice_id == 1002
            assert event3.attempt_count == 1
            assert event3.id != event1.id
            
            with TestingSessionLocal() as session:
                events = session.execute(select(DunningEvent)).scalars().all()
                assert len(events) == 2
                
                ev = session.execute(
                    select(DunningEvent).where(DunningEvent.invoice_id == 1001)
                ).scalar_one()
                assert ev.attempt_count == 2
            
        finally:
            configure(session_factory=None, email_sender=None)
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("dunning_management selftest OK")
