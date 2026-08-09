"""
credit_note — Credit notes (AR corrections/returns) applied against invoice balances.

### PART-META-JSON
{
  "name": "credit_note",
  "layer": "billing",
  "purpose": "Create credit notes and line items and apply them against an invoice balance table (accounts-receivable side).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "create_credit_note(invoice_id, amount>0); apply_credit_note(session, invoice_id, credit_note_id).",
  "outputs": "CreditNote / CreditNoteItem rows; InvoiceBalance row balance decremented atomically on apply.",
  "files_created": [],
  "security_notes": "Money-touching part. Over-credit guard: apply_credit_note decrements balance with a single conditional UPDATE (balance >= amount) so a credit can never push the balance negative, and a mismatch between the note's invoice_id and the target invoice is rejected before any write. create_credit_note rejects non-positive amounts. Known limitation: amounts are Float columns (not integer cents) - keep amounts to 2 decimal places and treat billing/invoices' amount_cents as the authoritative AR ledger; there is no idempotency key, so callers must not retry apply_credit_note after a successful commit (status='applied' is the reentry check).",
  "ai_usage": "Import from `scrapyard.billing.credit_note`; this part's InvoiceBalance table ('credit_note_invoice') is its own AR balance projection, distinct from the canonical billing/invoices Invoice model.",
  "example": "from scrapyard.billing.credit_note import create_credit_note, apply_credit_note",
  "import_path": "scrapyard.billing.credit_note"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, func, text
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

STATUS = "core"


class CreditNote(IntPKModel):
    """Credit note for invoice corrections and returns."""
    __tablename__ = "credit_note"
    
    invoice_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class CreditNoteItem(IntPKModel):
    """Line item within a credit note."""
    __tablename__ = "credit_note_item"

    credit_note_id: Mapped[int] = mapped_column(ForeignKey("credit_note.id"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)


class InvoiceBalance(IntPKModel):
    """AR balance projection this part credits against.

    This is credit_note's own table ('credit_note_invoice'), NOT the canonical
    billing/invoices Invoice model — apply_credit_note's raw SQL targets it.
    """
    __tablename__ = "credit_note_invoice"

    balance: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)


def create_credit_note(invoice_id: int, amount: float) -> CreditNote:
    """Create a new credit note linked to an invoice.

    Args:
        invoice_id: The ID of the invoice to credit
        amount: The credit amount (must be > 0)

    Returns:
        A new CreditNote instance with status 'draft'
    """
    if not (isinstance(amount, (int, float)) and amount > 0):
        raise ValueError("Credit amount must be a positive number")
    return CreditNote(invoice_id=invoice_id, amount=amount, status="draft")


def apply_credit_note(session: Session, invoice_id: int, credit_note_id: int) -> None:
    """Apply a credit note to an invoice, updating the invoice balance.
    
    Args:
        session: The database session
        invoice_id: The invoice ID to apply credit to
        credit_note_id: The credit note ID to apply
        
    Raises:
        ValueError: If credit note not found, not linked to invoice, or invoice not found
    """
    credit_note = session.get(CreditNote, credit_note_id)
    if credit_note is None:
        raise ValueError(f"Credit note {credit_note_id} not found")

    if credit_note.invoice_id != invoice_id:
        raise ValueError(f"Credit note {credit_note_id} does not belong to invoice {invoice_id}")

    if credit_note.status == "applied":
        raise ValueError(f"Credit note {credit_note_id} has already been applied")

    # Conditional UPDATE doubles as the over-credit guard: the balance can
    # never go negative because rows with balance < amount are not matched.
    result = session.execute(
        text(
            "UPDATE credit_note_invoice SET balance = balance - :amount "
            "WHERE id = :invoice_id AND balance >= :amount"
        ),
        {"amount": credit_note.amount, "invoice_id": invoice_id}
    )
    if result.rowcount == 0:
        exists = session.execute(
            text("SELECT balance FROM credit_note_invoice WHERE id = :invoice_id"),
            {"invoice_id": invoice_id}
        ).first()
        if exists is None:
            raise ValueError(f"Invoice {invoice_id} not found")
        raise ValueError(
            f"Credit note {credit_note_id} amount {credit_note.amount} exceeds "
            f"invoice {invoice_id} balance {exists[0]}"
        )

    credit_note.status = "applied"


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    import tempfile
    import os
    from sqlalchemy import create_engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)

        IntPKModel.metadata.create_all(engine)

        with Session(engine) as session:
            invoice = InvoiceBalance(balance=100.0, total=100.0)
            session.add(invoice)
            session.commit()
            
            cn = create_credit_note(invoice_id=invoice.id, amount=25.0)
            assert cn.invoice_id == invoice.id
            assert cn.amount == 25.0
            assert cn.status == "draft"
            
            session.add(cn)
            session.commit()
            assert cn.id is not None
            
            item = CreditNoteItem(credit_note_id=cn.id, item_id=1, quantity=2, amount=12.5)
            session.add(item)
            session.commit()
            assert item.id is not None
            assert item.credit_note_id == cn.id
            assert item.quantity == 2
            
            apply_credit_note(session, invoice.id, cn.id)
            session.commit()
            
            session.refresh(cn)
            assert cn.status == "applied"
            
            session.refresh(invoice)
            assert invoice.balance == 75.0
            
            try:
                apply_credit_note(session, invoice.id, 99999)
                assert False, "Should raise ValueError for missing credit note"
            except ValueError as e:
                assert "not found" in str(e)
            
            cn2 = create_credit_note(invoice_id=invoice.id, amount=10.0)
            session.add(cn2)
            session.commit()
            
            try:
                apply_credit_note(session, 99999, cn2.id)
                assert False, "Should raise ValueError for mismatched invoice"
            except ValueError as e:
                assert "does not belong" in str(e)
            
            cn3 = create_credit_note(invoice_id=88888, amount=5.0)
            session.add(cn3)
            session.commit()
            try:
                apply_credit_note(session, 88888, cn3.id)
                assert False, "Should raise ValueError for missing invoice"
            except ValueError as e:
                assert "Invoice" in str(e) and "not found" in str(e)

            # Over-credit guard: amount larger than remaining balance is refused
            cn4 = create_credit_note(invoice_id=invoice.id, amount=500.0)
            session.add(cn4)
            session.commit()
            try:
                apply_credit_note(session, invoice.id, cn4.id)
                assert False, "Should raise ValueError for over-credit"
            except ValueError as e:
                assert "exceeds" in str(e)
            session.refresh(invoice)
            assert invoice.balance == 75.0  # unchanged

            # Double-apply guard
            try:
                apply_credit_note(session, invoice.id, cn.id)
                assert False, "Should raise ValueError for already-applied note"
            except ValueError as e:
                assert "already" in str(e)

            # Non-positive amounts are rejected at creation
            try:
                create_credit_note(invoice_id=invoice.id, amount=0)
                assert False, "Should raise ValueError for zero amount"
            except ValueError:
                pass

        engine.dispose()
        logger.info("Self-test passed")


if __name__ == "__main__":
    _selftest()
    print("credit_note selftest OK")
