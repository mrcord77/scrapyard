"""
invoice_lifecycle — State machine for invoice lifecycle transitions with history.

### PART-META-JSON
{
  "name": "invoice_lifecycle",
  "layer": "billing",
  "purpose": "Enforce a validated invoice state machine (DRAFT/SENT/PAID/OVERDUE/CANCELLED/REFUNDED/DISPUTED/CLOSED) over the canonical billing/invoices Invoice model, with an auxiliary state table and append-only transition history.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure(engine); transition_invoice_state(invoice_id, new_state) with new_state an InvoiceState value string.",
  "outputs": "bool success. Lifecycle state stored in 'invoice_lifecycle_state' (one row per canonical invoice), history in 'invoice_state_history'; canonical Invoice.status is synced (PAID->paid, CANCELLED->void, else open).",
  "files_created": [],
  "security_notes": "Money-adjacent state machine: transitions are whitelist-validated (no arbitrary state jumps, terminal states CANCELLED/CLOSED reject all transitions), idempotent re-application does not duplicate history, and every applied transition is recorded append-only for audit. Risk: transition_invoice_state returns False on failure rather than raising, so callers MUST check the return value - ignoring it can silently drop a PAID transition.",
  "ai_usage": "Import from `scrapyard.billing.invoice_lifecycle`; the Invoice model itself is owned by scrapyard.billing.invoices - create invoices there, drive states here.",
  "example": "from scrapyard.billing.invoice_lifecycle import transition_invoice_state, InvoiceState",
  "import_path": "scrapyard.billing.invoice_lifecycle"
}
### END-PART-META
"""

from enum import Enum
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy import String, DateTime, ForeignKey, select, func, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from scrapyard.billing.invoices import Invoice, record_invoice
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

STATUS = "core"


class InvoiceState(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    DISPUTED = "DISPUTED"
    CLOSED = "CLOSED"


_VALID_TRANSITIONS: dict[InvoiceState, set[InvoiceState]] = {
    InvoiceState.DRAFT: {InvoiceState.SENT, InvoiceState.CANCELLED},
    InvoiceState.SENT: {InvoiceState.PAID, InvoiceState.OVERDUE, InvoiceState.DISPUTED, InvoiceState.CANCELLED},
    InvoiceState.PAID: {InvoiceState.REFUNDED, InvoiceState.CLOSED},
    InvoiceState.OVERDUE: {InvoiceState.PAID, InvoiceState.DISPUTED, InvoiceState.CANCELLED},
    InvoiceState.DISPUTED: {InvoiceState.PAID, InvoiceState.CANCELLED, InvoiceState.REFUNDED},
    InvoiceState.REFUNDED: {InvoiceState.CLOSED},
    InvoiceState.CANCELLED: set(),
    InvoiceState.CLOSED: set(),
}

# Sync map: lifecycle state -> canonical Invoice.status (open|paid|void)
_CANONICAL_STATUS: dict[InvoiceState, str] = {
    InvoiceState.PAID: "paid",
    InvoiceState.CANCELLED: "void",
}


class InvoiceLifecycleState(IntPKModel):
    """Current lifecycle state for a canonical invoice (one row per invoice)."""
    __tablename__ = "invoice_lifecycle_state"

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices_invoices.id"), nullable=False, unique=True, index=True
    )
    state: Mapped[str] = mapped_column(String(50), default=InvoiceState.DRAFT.value, nullable=False)


class InvoiceStateHistory(IntPKModel):
    __tablename__ = "invoice_state_history"

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices_invoices.id"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    transition_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


_engine: Optional[Any] = None
_SessionFactory: Optional[Any] = None


def configure(engine: Any) -> None:
    """Configure the module with a SQLAlchemy engine."""
    global _engine, _SessionFactory
    _engine = engine
    _SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


def get_invoice_state(session: Session, invoice_id: int) -> Optional[InvoiceState]:
    """Return the lifecycle state of an invoice (DRAFT if none recorded), or None if missing."""
    if session.get(Invoice, invoice_id) is None:
        return None
    row = session.scalar(
        select(InvoiceLifecycleState).where(InvoiceLifecycleState.invoice_id == invoice_id)
    )
    return InvoiceState(row.state) if row else InvoiceState.DRAFT


def transition_invoice_state(invoice_id: int, new_state: str) -> bool:
    """
    Transition an invoice to a new state if valid.

    Args:
        invoice_id: The ID of the canonical invoice to transition.
        new_state: The target state string (must match InvoiceState value).

    Returns:
        True if the transition was successful or idempotent (already in target state).
        False if the transition is invalid, invoice not found, or not configured.
    """
    if _SessionFactory is None:
        logger.error("Database not configured. Call configure() first.")
        return False

    try:
        target_state = InvoiceState(new_state)
    except ValueError:
        logger.warning(f"Invalid state value provided: {new_state}")
        return False

    session: Session = _SessionFactory()
    try:
        invoice = session.get(Invoice, invoice_id)
        if invoice is None:
            logger.warning(f"Invoice {invoice_id} not found")
            return False

        state_row = session.scalar(
            select(InvoiceLifecycleState).where(InvoiceLifecycleState.invoice_id == invoice_id)
        )
        if state_row is None:
            state_row = InvoiceLifecycleState(invoice_id=invoice_id, state=InvoiceState.DRAFT.value)
            session.add(state_row)

        current_state = InvoiceState(state_row.state)

        # Idempotency: already in target state
        if current_state == target_state:
            session.commit()
            return True

        # Validate transition
        allowed_next_states = _VALID_TRANSITIONS.get(current_state, set())
        if target_state not in allowed_next_states:
            logger.warning(f"Invalid transition attempt: {current_state.value} -> {target_state.value}")
            session.rollback()
            return False

        # Perform transition
        state_row.state = target_state.value

        # Keep the canonical invoice status in sync
        if target_state in _CANONICAL_STATUS:
            invoice.status = _CANONICAL_STATUS[target_state]
        elif target_state in (InvoiceState.DRAFT, InvoiceState.SENT,
                              InvoiceState.OVERDUE, InvoiceState.DISPUTED):
            invoice.status = "open"
        # REFUNDED / CLOSED keep the prior canonical status

        # Log to history
        history_entry = InvoiceStateHistory(
            invoice_id=invoice_id,
            state=target_state.value,
            notes=f"Transitioned from {current_state.value}"
        )
        session.add(history_entry)

        session.commit()
        return True

    except Exception as e:
        session.rollback()
        logger.error(f"Error during state transition: {e}")
        return False
    finally:
        session.close()


def _selftest() -> None:
    """Self-contained unit tests using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)

        configure(engine)
        IntPKModel.metadata.create_all(engine)

        # Create test invoice via the canonical part
        with Session(engine) as session:
            inv = record_invoice(session, user_id=1, amount_cents=5000)
            session.commit()
            test_invoice_id = inv.id

        try:
            # Test 1: Valid transition DRAFT -> SENT
            assert transition_invoice_state(test_invoice_id, "SENT") is True

            # Test 2: Verify history logging
            with Session(engine) as session:
                history = session.scalars(
                    select(InvoiceStateHistory).where(InvoiceStateHistory.invoice_id == test_invoice_id)
                ).all()
                assert len(history) == 1
                assert history[0].state == "SENT"
                assert "DRAFT" in history[0].notes

            # Test 3: Invalid transition SENT -> DRAFT (backwards)
            assert transition_invoice_state(test_invoice_id, "DRAFT") is False

            # Test 4: Valid transition SENT -> PAID syncs canonical status
            assert transition_invoice_state(test_invoice_id, InvoiceState.PAID.value) is True
            with Session(engine) as session:
                assert session.get(Invoice, test_invoice_id).status == "paid"
                assert get_invoice_state(session, test_invoice_id) is InvoiceState.PAID

            # Test 5: Idempotency - PAID -> PAID should return True without new history
            with Session(engine) as session:
                count_before = session.scalar(
                    select(func.count()).select_from(InvoiceStateHistory).where(InvoiceStateHistory.invoice_id == test_invoice_id)
                )

            assert transition_invoice_state(test_invoice_id, "PAID") is True

            with Session(engine) as session:
                count_after = session.scalar(
                    select(func.count()).select_from(InvoiceStateHistory).where(InvoiceStateHistory.invoice_id == test_invoice_id)
                )
                assert count_before == count_after, "Idempotency should not create duplicate history"

            # Test 6: Invalid state string
            assert transition_invoice_state(test_invoice_id, "INVALID_STATE") is False

            # Test 7: Non-existent invoice
            assert transition_invoice_state(99999, "CLOSED") is False

            # Test 8: Terminal state validation (CLOSED is terminal)
            assert transition_invoice_state(test_invoice_id, "CLOSED") is True  # PAID -> CLOSED valid
            assert transition_invoice_state(test_invoice_id, "REFUNDED") is False  # CLOSED -> REFUNDED invalid

            # Test 9: fresh invoice defaults to DRAFT without a state row
            with Session(engine) as session:
                inv2 = record_invoice(session, user_id=2, amount_cents=100)
                session.commit()
                assert get_invoice_state(session, inv2.id) is InvoiceState.DRAFT
                assert get_invoice_state(session, 424242) is None

        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("invoice_lifecycle selftest OK")
