"""
vendor_management — Canonical procurement models: vendors, POs, receipts, spend.

### PART-META-JSON
{
  "name": "vendor_management",
  "layer": "procurement_vend",
  "purpose": "Own the canonical procurement models (Vendor, VendorContact, PurchaseOrder, LineItem, Receipt, ReceiptItem, SpendCategory, SpendEntry) and the vendor/PO/receipt/spend API; sibling parts (invoice_matching, spend_tracking) import these models instead of redefining them.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "create_vendor, update_vendor_contact, create_purchase_order, update_po_status, receive_shipment, match_po_to_receipt, record_spend, generate_spend_report - all take an explicit Session.",
  "outputs": "ORM rows in tables vendors / vendor_contacts / vendor_management_purchase_orders / vendor_management_line_items / receipts / receipt_items / vendor_management_spend_categories / vendor_management_spend_entries.",
  "files_created": [],
  "security_notes": "Money-touching part (PO totals, spend entries). record_spend validates vendor and category existence and rejects negative amounts; PO totals are computed from line items, not caller-supplied. Amounts are Float columns - acceptable for analytics, but do not use these totals as an authoritative ledger without rounding discipline (2dp). Vendor tax_id is sensitive - do not log it. Purchase orders here are the PROCUREMENT (accounts-payable) side; customer invoices live in billing/invoices (AR) - deliberately separate models and tables.",
  "ai_usage": "Import models and API from `scrapyard.procurement_vend.vendor_management`; other procurement parts must import these models rather than declaring their own PO/spend tables.",
  "example": "from scrapyard.procurement_vend.vendor_management import Vendor, create_vendor",
  "import_path": "scrapyard.procurement_vend.vendor_management"
}
### END-PART-META
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging
import os
import tempfile

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# ORM models
# ------------------------------------------------------------------------------

class Vendor(IntPKModel):
    __tablename__ = "vendors"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tax_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    contacts: Mapped[List["VendorContact"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )
    purchase_orders: Mapped[List["PurchaseOrder"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )
    spend_entries: Mapped[List["SpendEntry"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )


class VendorContact(IntPKModel):
    __tablename__ = "vendor_contacts"

    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    vendor: Mapped["Vendor"] = relationship(back_populates="contacts")


class PurchaseOrder(IntPKModel):
    __tablename__ = "vendor_management_purchase_orders"

    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False)
    po_number: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    order_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    vendor: Mapped["Vendor"] = relationship(back_populates="purchase_orders")
    line_items: Mapped[List["LineItem"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )
    receipts: Mapped[List["Receipt"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class LineItem(IntPKModel):
    __tablename__ = "vendor_management_line_items"

    po_id: Mapped[int] = mapped_column(
        ForeignKey("vendor_management_purchase_orders.id"), nullable=False
    )
    item_number: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="line_items")
    receipt_items: Mapped[List["ReceiptItem"]] = relationship(
        back_populates="line_item", cascade="all, delete-orphan"
    )


class Receipt(IntPKModel):
    __tablename__ = "receipts"

    po_id: Mapped[int] = mapped_column(
        ForeignKey("vendor_management_purchase_orders.id"), nullable=False
    )
    receipt_number: Mapped[str] = mapped_column(String(128), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="receipts")
    receipt_items: Mapped[List["ReceiptItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )


class ReceiptItem(IntPKModel):
    __tablename__ = "receipt_items"

    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("receipts.id"), nullable=False
    )
    line_item_id: Mapped[int] = mapped_column(
        ForeignKey("vendor_management_line_items.id"), nullable=False
    )
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    receipt: Mapped["Receipt"] = relationship(back_populates="receipt_items")
    line_item: Mapped["LineItem"] = relationship(back_populates="receipt_items")


class SpendCategory(IntPKModel):
    __tablename__ = "vendor_management_spend_categories"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    spend_entries: Mapped[List["SpendEntry"]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class SpendEntry(IntPKModel):
    __tablename__ = "vendor_management_spend_entries"

    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("vendor_management_spend_categories.id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entry_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    vendor: Mapped["Vendor"] = relationship(back_populates="spend_entries")
    category: Mapped["SpendCategory"] = relationship(back_populates="spend_entries")


# ------------------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------------------

def create_vendor(
    session: Session,
    name: str,
    code: str = "",
    tax_id: str = "",
    address: str = "",
    status: str = "active",
) -> Vendor:
    """
    Create a new vendor record.
    """
    if not name or not isinstance(name, str):
        raise ValueError("Vendor name must be a non-empty string.")

    vendor = Vendor(
        name=name,
        code=code or "",
        tax_id=tax_id or "",
        address=address or "",
        status=status or "active",
    )
    session.add(vendor)
    session.commit()
    session.refresh(vendor)
    return vendor


def update_vendor_contact(
    session: Session, contact_id: int, **kwargs: Any
) -> Optional[VendorContact]:
    """
    Update a vendor contact. Only safe, existing fields are updated.
    """
    contact = session.get(VendorContact, contact_id)
    if contact is None:
        return None

    allowed = {"name", "email", "phone", "is_primary"}
    for key, value in kwargs.items():
        if key in allowed:
            setattr(contact, key, value)

    session.commit()
    session.refresh(contact)
    return contact


def create_purchase_order(
    session: Session,
    vendor_id: int,
    po_number: str,
    line_items: List[Dict[str, Any]],
    order_date: Optional[datetime] = None,
    notes: str = "",
) -> PurchaseOrder:
    """
    Create a purchase order with line items.
    """
    vendor = session.get(Vendor, vendor_id)
    if vendor is None:
        raise ValueError(f"Vendor {vendor_id} not found.")
    if not po_number or not isinstance(po_number, str):
        raise ValueError("PO number must be a non-empty string.")

    po = PurchaseOrder(
        vendor_id=vendor_id,
        po_number=po_number,
        order_date=order_date or datetime.now(timezone.utc),
        notes=notes or "",
    )
    session.add(po)
    # flush to get po.id for line items
    session.flush()

    total = 0.0
    for item in line_items or []:
        qty = int(item.get("quantity", 0))
        price = float(item.get("unit_price", 0.0))
        line_total = qty * price
        total += line_total

        li = LineItem(
            po_id=po.id,
            item_number=str(item.get("item_number", "")),
            description=str(item.get("description", "")),
            quantity=qty,
            unit_price=price,
            line_total=line_total,
        )
        session.add(li)

    po.total = total
    session.commit()
    session.refresh(po)
    return po


def update_po_status(
    session: Session, po_id: int, status: str
) -> Optional[PurchaseOrder]:
    """
    Update the status of a purchase order.
    """
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        return None

    po.status = status
    session.commit()
    session.refresh(po)
    return po


def receive_shipment(
    session: Session,
    po_id: int,
    receipt_number: str,
    items: List[Dict[str, Any]],
    received_at: Optional[datetime] = None,
) -> Receipt:
    """
    Record a shipment receipt against a purchase order.
    """
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        raise ValueError(f"Purchase order {po_id} not found.")
    if not receipt_number or not isinstance(receipt_number, str):
        raise ValueError("Receipt number must be a non-empty string.")

    receipt = Receipt(
        po_id=po_id,
        receipt_number=receipt_number,
        received_at=received_at or datetime.now(timezone.utc),
    )
    session.add(receipt)
    session.flush()

    po_line_ids = {li.id for li in po.line_items}
    for item in items or []:
        line_item_id = int(item.get("line_item_id", 0))
        qty = int(item.get("quantity_received", 0))

        if line_item_id not in po_line_ids:
            raise ValueError(
                f"Line item {line_item_id} does not belong to PO {po_id}."
            )

        ri = ReceiptItem(
            receipt_id=receipt.id,
            line_item_id=line_item_id,
            quantity_received=qty,
        )
        session.add(ri)

    session.commit()
    session.refresh(receipt)
    return receipt


def match_po_to_receipt(session: Session, po_id: int, receipt_id: int) -> bool:
    """
    Verify that a receipt matches a purchase order.
    """
    po = session.get(PurchaseOrder, po_id)
    receipt = session.get(Receipt, receipt_id)
    if po is None or receipt is None:
        return False

    if receipt.po_id is None:
        receipt.po_id = po_id
    elif receipt.po_id != po_id:
        return False

    po_line_ids = {li.id for li in po.line_items}
    for ri in receipt.receipt_items:
        if ri.line_item_id not in po_line_ids:
            return False

    session.commit()
    session.refresh(receipt)
    return True


def record_spend(
    session: Session,
    vendor_id: int,
    category_id: int,
    amount: float,
    entry_date: Optional[datetime] = None,
    description: str = "",
) -> SpendEntry:
    """
    Record a spend entry against a vendor and category.
    """
    vendor = session.get(Vendor, vendor_id)
    if vendor is None:
        raise ValueError(f"Vendor {vendor_id} not found.")
    category = session.get(SpendCategory, category_id)
    if category is None:
        raise ValueError(f"Spend category {category_id} not found.")
    if amount < 0:
        raise ValueError("Spend amount cannot be negative.")

    entry = SpendEntry(
        vendor_id=vendor_id,
        category_id=category_id,
        amount=float(amount),
        entry_date=entry_date or datetime.now(timezone.utc),
        description=description or "",
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def generate_spend_report(
    session: Session,
    vendor_id: Optional[int] = None,
    category_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Generate a simple spend report, optionally filtered by vendor or category.
    """
    stmt = select(SpendEntry)
    if vendor_id is not None:
        stmt = stmt.where(SpendEntry.vendor_id == vendor_id)
    if category_id is not None:
        stmt = stmt.where(SpendEntry.category_id == category_id)

    entries = list(session.execute(stmt).scalars().all())
    total = float(sum(entry.amount for entry in entries))

    return {
        "total": total,
        "count": len(entries),
        "entries": [
            {
                "id": entry.id,
                "vendor_id": entry.vendor_id,
                "category_id": entry.category_id,
                "amount": entry.amount,
                "entry_date": entry.entry_date,
                "description": entry.description,
            }
            for entry in entries
        ],
    }


# ------------------------------------------------------------------------------
# Self-test
# ------------------------------------------------------------------------------

def _selftest() -> None:
    """
    Offline self-test for vendor_management.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_vendor_management.db")
        engine = create_engine(f"sqlite:///{db_path}", future=True, echo=False)

        # Create all tables
        IntPKModel.metadata.create_all(engine)

        with Session(engine) as session:
            # Vendor creation and contact update
            vendor = create_vendor(
                session,
                name="Acme Supplies",
                code="ACM-001",
                tax_id="TAX-123",
                address="123 Industrial Way",
            )
            assert isinstance(vendor, Vendor)
            assert vendor.id is not None
            assert vendor.name == "Acme Supplies"

            contact = VendorContact(
                vendor_id=vendor.id,
                name="Jane Doe",
                email="jane@example.com",
                phone="555-0000",
                is_primary=True,
            )
            session.add(contact)
            session.commit()
            session.refresh(contact)

            updated_contact = update_vendor_contact(
                session, contact.id, phone="555-9999", email="jane.doe@example.com"
            )
            assert updated_contact is not None
            assert updated_contact.phone == "555-9999"
            assert updated_contact.email == "jane.doe@example.com"

            # Purchase order with line items
            po = create_purchase_order(
                session,
                vendor_id=vendor.id,
                po_number="PO-2024-0001",
                line_items=[
                    {
                        "item_number": "WGT-A",
                        "description": "Widget A",
                        "quantity": 10,
                        "unit_price": 2.5,
                    },
                    {
                        "item_number": "WGT-B",
                        "description": "Widget B",
                        "quantity": 5,
                        "unit_price": 4.0,
                    },
                ],
                notes="Initial order",
            )
            assert isinstance(po, PurchaseOrder)
            assert po.total == 45.0
            assert len(po.line_items) == 2

            po_updated = update_po_status(session, po.id, "approved")
            assert po_updated is not None
            assert po_updated.status == "approved"

            # Receive shipment
            receipt = receive_shipment(
                session,
                po_id=po.id,
                receipt_number="REC-2024-0001",
                items=[
                    {"line_item_id": po.line_items[0].id, "quantity_received": 10},
                    {"line_item_id": po.line_items[1].id, "quantity_received": 5},
                ],
            )
            assert isinstance(receipt, Receipt)
            assert receipt.po_id == po.id
            assert len(receipt.receipt_items) == 2

            matched = match_po_to_receipt(session, po.id, receipt.id)
            assert matched is True

            # Spend tracking
            category = SpendCategory(
                name="Hardware", description="Hardware and tooling"
            )
            session.add(category)
            session.commit()
            session.refresh(category)

            entry = record_spend(
                session,
                vendor_id=vendor.id,
                category_id=category.id,
                amount=123.45,
                description="Test spend entry",
            )
            assert isinstance(entry, SpendEntry)
            assert entry.amount == 123.45

            report = generate_spend_report(session, vendor_id=vendor.id)
            assert isinstance(report, dict)
            assert report["total"] == 123.45
            assert report["count"] == 1
            assert len(report["entries"]) == 1

            # Invalid input handling
            try:
                create_vendor(session, "")
                raise AssertionError("Expected ValueError for empty vendor name")
            except ValueError:
                pass

            invalid_update = update_po_status(session, 999999, "closed")
            assert invalid_update is None

            try:
                record_spend(session, vendor_id=999999, category_id=category.id, amount=10.0)
                raise AssertionError("Expected ValueError for missing vendor")
            except ValueError:
                pass

            # Verify all tables are queryable
            models = [
                Vendor,
                VendorContact,
                PurchaseOrder,
                LineItem,
                Receipt,
                ReceiptItem,
                SpendCategory,
                SpendEntry,
            ]
            for model in models:
                result = session.execute(select(model)).scalars().all()
                assert isinstance(result, list)

        engine.dispose()

    logger.info("scrapyard.procurement_vend.vendor_management _selftest passed")


if __name__ == "__main__":
    _selftest()
