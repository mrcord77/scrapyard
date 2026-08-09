"""
invoice_matching — Match vendor (AP) invoices to canonical purchase orders.

### PART-META-JSON
{
  "name": "invoice_matching",
  "layer": "procurement_vend",
  "purpose": "Two-way match vendor invoices against purchase orders (line item codes + quantities) and validate totals/currency. PurchaseOrder/LineItem are IMPORTED from vendor_management (canonical owner); the AP Invoice/InvoiceLine models are owned here.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "match_invoice_to_po(po_id, invoice) with a session-bound Invoice; validate_invoice(invoice).",
  "outputs": "Matched InvoiceLine lists; ValidationResult(is_valid, errors). Tables: 'invoice_matching_invoices' / 'invoice_lines' (owned), 'vendor_management_purchase_orders' / 'vendor_management_line_items' (imported).",
  "files_created": [],
  "security_notes": "Money-touching control: this IS the over-payment guard for accounts payable - totals are recomputed from invoice lines and cross-checked against the PO total and currency with a 0.01 tolerance (float epsilon; adequate for 2dp currencies, do not use for 0dp/3dp currencies without adjusting the tolerance). NOTE: this Invoice is the ACCOUNTS-PAYABLE vendor bill (what we owe suppliers); customer invoices live in billing/invoices (AR) - same word, different ledger, deliberately distinct tables. Matching trusts item codes as opaque strings; no expression evaluation.",
  "ai_usage": "Import from `scrapyard.procurement_vend.invoice_matching`; create POs via vendor_management, then attach Invoice/InvoiceLine rows and run validate_invoice before approving payment.",
  "example": "from scrapyard.procurement_vend.invoice_matching import validate_invoice",
  "import_path": "scrapyard.procurement_vend.invoice_matching"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship, object_session
from scrapyard.database.base_model import IntPKModel

# Canonical procurement models - owned by vendor_management, imported here.
from scrapyard.procurement_vend.vendor_management import PurchaseOrder, LineItem

from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

STATUS = "core"


class Invoice(IntPKModel):
    """Vendor (accounts-payable) invoice header matched to purchase orders.

    Distinct from billing/invoices (accounts receivable) by design.
    """
    __tablename__ = "invoice_matching_invoices"

    po_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    total: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    lines: Mapped[List["InvoiceLine"]] = relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLine(IntPKModel):
    """Individual line items on a vendor invoice."""
    __tablename__ = "invoice_lines"

    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoice_matching_invoices.id"), nullable=False, index=True)
    item_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    tax_code: Mapped[str] = mapped_column(String(20), nullable=True)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="lines")


@dataclass
class ValidationResult:
    """Result of invoice validation."""
    is_valid: bool = False
    errors: List[str] = field(default_factory=list)


def match_invoice_to_po(po_id: int, invoice: Invoice) -> List[InvoiceLine]:
    """
    Match invoice lines to purchase order lines by item code and quantity.
    Invoice line item_code is matched against the canonical LineItem.item_number.
    Returns invoice lines that have corresponding PO lines with matching item codes and quantities.
    """
    matched_lines: List[InvoiceLine] = []

    if invoice.po_id != po_id:
        return matched_lines

    session = object_session(invoice)
    if session is None:
        logger.error("Invoice is not bound to a session")
        return matched_lines

    stmt = select(LineItem).where(LineItem.po_id == po_id)
    po_lines = session.execute(stmt).scalars().all()

    po_lines_map = {line.item_number: line for line in po_lines}

    for inv_line in invoice.lines:
        po_line = po_lines_map.get(inv_line.item_code)
        if po_line is not None:
            if abs(inv_line.quantity - po_line.quantity) < 0.01:
                matched_lines.append(inv_line)

    return matched_lines


def validate_invoice(invoice: Invoice) -> ValidationResult:
    """
    Validate invoice totals and currency against purchase order and line items.
    """
    errors: List[str] = []

    calculated_total = sum(line.quantity * line.unit_price for line in invoice.lines)
    if abs(invoice.total - calculated_total) > 0.01:
        errors.append(f"Line total mismatch: sum of lines is {calculated_total}, invoice total is {invoice.total}")

    session = object_session(invoice)
    if session is not None:
        stmt = select(PurchaseOrder).where(PurchaseOrder.id == invoice.po_id)
        po = session.execute(stmt).scalar_one_or_none()

        if po is None:
            errors.append(f"Purchase order {invoice.po_id} not found")
        else:
            if invoice.currency != po.currency:
                errors.append(f"Currency mismatch: invoice {invoice.currency}, PO {po.currency}")

            if abs(invoice.total - po.total) > 0.01:
                errors.append(f"Total mismatch: invoice {invoice.total}, PO {po.total}")
    else:
        if invoice.total < 0:
            errors.append("Invoice total cannot be negative")
        if not invoice.currency:
            errors.append("Currency is required")

    return ValidationResult(is_valid=len(errors) == 0, errors=errors)


def _selftest() -> None:
    """Offline self-test suite using temporary SQLite."""
    from scrapyard.procurement_vend.vendor_management import Vendor

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_invoice_matching.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)

        IntPKModel.metadata.create_all(engine)

        with Session(engine) as session:
            vendor = Vendor(name="Acme Supply")
            session.add(vendor)
            session.flush()

            po = PurchaseOrder(vendor_id=vendor.id, po_number="PO-1", currency="USD", total=1000.00)
            session.add(po)
            session.flush()

            po_line1 = LineItem(po_id=po.id, item_number="ENG-001", quantity=2, unit_price=100.0, line_total=200.0)
            po_line2 = LineItem(po_id=po.id, item_number="ENG-002", quantity=5, unit_price=160.0, line_total=800.0)
            session.add_all([po_line1, po_line2])
            session.commit()

            invoice = Invoice(po_id=po.id, total=1000.00, currency="USD")
            line1 = InvoiceLine(invoice=invoice, item_code="ENG-001", quantity=2.0, unit_price=100.0, tax_code="TAX-A")
            line2 = InvoiceLine(invoice=invoice, item_code="ENG-002", quantity=5.0, unit_price=160.0, tax_code="TAX-A")
            session.add(invoice)
            session.commit()

            stmt = select(Invoice).where(Invoice.id == invoice.id)
            inv_check = session.execute(stmt).scalar_one()
            assert inv_check is not None
            assert len(inv_check.lines) == 2

            matched = match_invoice_to_po(po.id, invoice)
            assert len(matched) == 2
            assert all(isinstance(l, InvoiceLine) for l in matched)

            valid_result = validate_invoice(invoice)
            assert valid_result.is_valid, f"Expected valid, got errors: {valid_result.errors}"

            bad_curr_inv = Invoice(po_id=po.id, total=1000.00, currency="EUR")
            bad_curr_line = InvoiceLine(invoice=bad_curr_inv, item_code="ENG-001", quantity=2.0, unit_price=500.0)
            session.add(bad_curr_inv)
            session.commit()

            bad_curr_result = validate_invoice(bad_curr_inv)
            assert not bad_curr_result.is_valid
            assert any("Currency mismatch" in e for e in bad_curr_result.errors)

            bad_total_inv = Invoice(po_id=po.id, total=500.00, currency="USD")
            bad_total_line = InvoiceLine(invoice=bad_total_inv, item_code="ENG-001", quantity=2.0, unit_price=250.0)
            session.add(bad_total_inv)
            session.commit()

            bad_total_result = validate_invoice(bad_total_inv)
            assert not bad_total_result.is_valid
            assert any("mismatch" in e.lower() for e in bad_total_result.errors)

            wrong_po_match = match_invoice_to_po(9999, invoice)
            assert len(wrong_po_match) == 0

            missing_po_inv = Invoice(po_id=424242, total=100.0, currency="USD")
            session.add(missing_po_inv)
            session.commit()
            missing_po_result = validate_invoice(missing_po_inv)
            assert not missing_po_result.is_valid
            assert any("not found" in e for e in missing_po_result.errors)

        engine.dispose()
        logger.info("_selftest completed successfully")


if __name__ == "__main__":
    _selftest()
    print("invoice_matching selftest OK")
