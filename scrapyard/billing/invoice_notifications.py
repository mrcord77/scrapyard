"""
invoice_notifications — Templated invoice notifications over the canonical Invoice model.

### PART-META-JSON
{
  "name": "invoice_notifications",
  "layer": "billing",
  "purpose": "Render notification templates for invoice events and record delivery, using the canonical billing/invoices Invoice model plus an auxiliary contact table (email/phone per invoice).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "_configure_engine(engine); send_invoice_notification(invoice_id, event_type); NotificationTemplate rows with {placeholder} subject/body; InvoiceContact rows for recipients.",
  "outputs": "Notification rows (status pending->sent). Delivery backend is an offline no-op placeholder; wire SMTP/Twilio in _deliver for production.",
  "files_created": [],
  "security_notes": "Template rendering is plain placeholder substitution (regex {name} lookup) - no eval, no format-string gadgets; unknown placeholders are left verbatim rather than erroring. Context exposes only invoice column values, so templates cannot reach arbitrary attributes. Recipient email/phone are PII stored in 'invoice_notifications_contact'; the default _deliver makes NO network calls (logs at debug), so nothing leaves the process offline. When wiring a real backend, rate-limit and verify recipients to avoid using this as a spam relay.",
  "ai_usage": "Import from `scrapyard.billing.invoice_notifications`; invoices come from scrapyard.billing.invoices; add an InvoiceContact row per invoice for routing.",
  "example": "from scrapyard.billing.invoice_notifications import send_invoice_notification",
  "import_path": "scrapyard.billing.invoice_notifications"
}
### END-PART-META
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import ForeignKey, String, Text, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel
from scrapyard.billing.invoices import Invoice, record_invoice

logger = logging.getLogger(__name__)

STATUS = "core"

__all__ = [
    "NotificationTemplate",
    "InvoiceContact",
    "send_invoice_notification",
]

_engine: Any = None
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class NotificationTemplate(IntPKModel):
    __tablename__ = "invoice_notifications_notification_template"

    event_type: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class Notification(IntPKModel):
    __tablename__ = "invoice_notifications_notification"

    event: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(default=None, nullable=True)
    recipient: Mapped[str] = mapped_column(String(500), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)


class InvoiceContact(IntPKModel):
    """Contact routing info for a canonical invoice (one row per invoice)."""
    __tablename__ = "invoice_notifications_contact"

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices_invoices.id"), nullable=False, unique=True, index=True
    )
    customer_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


def _configure_engine(engine: Any) -> None:
    global _engine
    _engine = engine


def _build_context(invoice: Invoice, contact: Optional[InvoiceContact], event_type: str) -> Dict[str, Any]:
    context: Dict[str, Any] = {"event_type": event_type}
    for column in invoice.__table__.columns:
        context[column.name] = getattr(invoice, column.name)
    context["invoice_id"] = invoice.id
    context["amount"] = invoice.amount_cents / 100.0
    if contact is not None:
        context["customer_email"] = contact.customer_email
        context["customer_phone"] = contact.customer_phone
    return context


def _substitute(text: str, context: Dict[str, Any]) -> str:
    def _repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in context:
            return str(context[key])
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_repl, text)


def _render_template(
    template: NotificationTemplate, invoice: Invoice,
    contact: Optional[InvoiceContact], event_type: str
) -> Tuple[str, str]:
    context = _build_context(invoice, contact, event_type)
    subject = _substitute(template.subject, context)
    body = _substitute(template.body, context)
    return subject, body


def _determine_channel_and_recipient(invoice: Invoice, contact: Optional[InvoiceContact]) -> Tuple[str, str]:
    if contact is not None and contact.customer_email:
        return "email", contact.customer_email
    if contact is not None and contact.customer_phone:
        return "sms", contact.customer_phone
    raise ValueError(f"Invoice {invoice.id} has no email or phone contact")


def _deliver(notification: Notification, channel: str, subject: str, body: str) -> None:
    # Default delivery backend is a safe no-op placeholder. No network calls are made.
    if channel not in {"email", "sms"}:
        raise ValueError(f"Unsupported notification channel: {channel}")
    # In a production deployment this would hand off to SMTP, Twilio, etc.
    logger.debug("Delivered %s notification to %s", channel, notification.recipient)


def send_invoice_notification(invoice_id: int, event_type: str) -> Notification:
    if _engine is None:
        raise RuntimeError("Invoice notification engine has not been configured")

    with Session(_engine) as session:
        invoice = session.get(Invoice, invoice_id)
        if invoice is None:
            raise ValueError(f"Invoice {invoice_id} not found")

        contact = session.scalar(
            select(InvoiceContact).where(InvoiceContact.invoice_id == invoice_id).limit(1)
        )

        template = session.scalar(
            select(NotificationTemplate)
            .where(NotificationTemplate.event_type == event_type)
            .limit(1)
        )
        if template is None:
            raise ValueError(f"No notification template for event type {event_type}")

        channel, recipient = _determine_channel_and_recipient(invoice, contact)
        subject, body = _render_template(template, invoice, contact, event_type)

        notification = Notification(
            event=event_type,
            status="pending",
            recipient=recipient,
            channel=channel,
        )
        session.add(notification)

        try:
            _deliver(notification, channel, subject, body)
            notification.status = "sent"
            notification.sent_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(notification)
        except Exception:
            session.rollback()
            logger.exception("Failed to send invoice notification")
            raise
        finally:
            session.expunge(notification)

        return notification


def _selftest() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        IntPKModel.metadata.create_all(engine)
        _configure_engine(engine)

        with Session(engine) as session:
            template = NotificationTemplate(
                event_type="created",
                subject="Invoice {invoice_id} created",
                body="Your invoice total is {amount}. Unknown {nope} stays literal.",
            )
            invoice = record_invoice(session, user_id=1, amount_cents=12345)
            session.add(template)
            session.flush()
            session.add(InvoiceContact(invoice_id=invoice.id, customer_email="test@example.com"))
            session.commit()
            invoice_id = invoice.id

        # Missing invoice should raise.
        try:
            send_invoice_notification(invoice_id + 9999, "created")
            raise AssertionError("Expected ValueError for missing invoice")
        except ValueError:
            pass

        # Missing template should raise.
        try:
            send_invoice_notification(invoice_id, "unknown_event")
            raise AssertionError("Expected ValueError for missing template")
        except ValueError:
            pass

        notification = send_invoice_notification(invoice_id, "created")

        assert isinstance(notification, Notification)
        assert notification.event == "created"
        assert notification.status == "sent"
        assert notification.recipient == "test@example.com"
        assert notification.channel == "email"
        assert notification.sent_at is not None

        # Rendering: placeholders resolve from canonical invoice columns
        with Session(engine) as session:
            inv = session.get(Invoice, invoice_id)
            contact = session.scalar(select(InvoiceContact).where(InvoiceContact.invoice_id == invoice_id))
            tpl = session.scalar(select(NotificationTemplate).where(NotificationTemplate.event_type == "created"))
            subject, body = _render_template(tpl, inv, contact, "created")
            assert subject == f"Invoice {invoice_id} created"
            assert "123.45" in body
            assert "{nope}" in body  # unknown placeholder left verbatim

        # Invoice with no contact info should raise.
        with Session(engine) as session:
            orphan = record_invoice(session, user_id=2, amount_cents=100)
            session.commit()
            orphan_id = orphan.id
        try:
            send_invoice_notification(orphan_id, "created")
            raise AssertionError("Expected ValueError for missing contact")
        except ValueError:
            pass

        with Session(engine) as session:
            stored = session.get(Notification, notification.id)
            assert stored is not None
            assert stored.event == "created"
            assert stored.status == "sent"
            assert stored.recipient == "test@example.com"
            assert stored.channel == "email"

        engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("invoice_notifications selftest OK")
