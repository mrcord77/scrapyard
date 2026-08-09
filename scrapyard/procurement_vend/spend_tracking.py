"""
spend_tracking — Date-ranged spend recording and reporting over the canonical models.

### PART-META-JSON
{
  "name": "spend_tracking",
  "layer": "procurement_vend",
  "purpose": "Record spend entries and generate date-range spend reports using the canonical SpendCategory/SpendEntry models owned by vendor_management (no duplicate tables).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "record_spend(vendor_id, category_id, amount, date, session); generate_spend_report(start_date, end_date, session).",
  "outputs": "SpendEntry rows in 'vendor_management_spend_entries' (models IMPORTED from scrapyard.procurement_vend.vendor_management); report dicts with id/vendor_id/category_id/amount/date/category_name.",
  "files_created": [],
  "security_notes": "Money-touching analytics. Inputs are type/range validated (positive ids, non-negative amount, datetime date, ordered date range). Amounts are Float columns (owned by the canonical model) - fine for reporting, not an authoritative ledger. Unlike vendor_management.record_spend, this variant does NOT verify the vendor/category rows exist (SQLite FKs unenforced by default) - callers own referential integrity.",
  "ai_usage": "Import from `scrapyard.procurement_vend.spend_tracking`; the model set is shared with vendor_management, so both parts read/write the same tables.",
  "example": "from scrapyard.procurement_vend.spend_tracking import record_spend",
  "import_path": "scrapyard.procurement_vend.spend_tracking"
}
### END-PART-META
"""

from sqlalchemy import select
from sqlalchemy.orm import Session
from scrapyard.database.base_model import IntPKModel

# Canonical models owned by vendor_management - imported, not redefined.
from scrapyard.procurement_vend.vendor_management import SpendCategory, SpendEntry

from datetime import datetime, timezone
from typing import List, Dict, Any
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

STATUS = "core"


def record_spend(vendor_id: int, category_id: int, amount: float, date: datetime, session: Session) -> SpendEntry:
    if not isinstance(vendor_id, int) or vendor_id <= 0:
        raise ValueError("vendor_id must be a positive integer")
    if not isinstance(category_id, int) or category_id <= 0:
        raise ValueError("category_id must be a positive integer")
    if not isinstance(amount, (int, float)) or amount < 0:
        raise ValueError("amount must be a non-negative number")
    if not isinstance(date, datetime):
        raise ValueError("date must be a datetime instance")

    entry = SpendEntry(
        vendor_id=vendor_id,
        category_id=category_id,
        amount=float(amount),
        entry_date=date,
    )
    session.add(entry)
    return entry


def generate_spend_report(start_date: datetime, end_date: datetime, session: Session) -> List[Dict[str, Any]]:
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")

    stmt = select(SpendEntry).where(
        SpendEntry.entry_date >= start_date,
        SpendEntry.entry_date <= end_date
    )

    result = session.execute(stmt)
    entries = result.scalars().all()

    return [
        {
            "id": entry.id,
            "vendor_id": entry.vendor_id,
            "category_id": entry.category_id,
            "amount": entry.amount,
            "date": entry.entry_date,
            "category_name": entry.category.name if entry.category else None
        }
        for entry in entries
    ]


def _selftest() -> None:
    from sqlalchemy import create_engine
    from scrapyard.procurement_vend.vendor_management import create_vendor

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)

        IntPKModel.metadata.create_all(engine)

        with Session(engine) as session:
            vendor = create_vendor(session, name="Test Vendor")
            cat = SpendCategory(name="Test Hardware", description="Hardware components")
            session.add(cat)
            session.commit()

            stmt = select(SpendCategory).where(SpendCategory.name == "Test Hardware")
            fetched_cat = session.execute(stmt).scalar_one_or_none()
            assert fetched_cat is not None, "SpendCategory not created"
            cat_id = fetched_cat.id

            try:
                record_spend(-1, cat_id, 100.0, datetime.now(timezone.utc), session)
                assert False, "Should raise ValueError for invalid vendor_id"
            except ValueError:
                pass

            try:
                record_spend(1, -1, 100.0, datetime.now(timezone.utc), session)
                assert False, "Should raise ValueError for invalid category_id"
            except ValueError:
                pass

            try:
                record_spend(1, cat_id, -100.0, datetime.now(timezone.utc), session)
                assert False, "Should raise ValueError for negative amount"
            except ValueError:
                pass

            test_date = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
            entry = record_spend(vendor.id, cat_id, 999.99, test_date, session)
            session.commit()

            assert entry.id is not None, "SpendEntry not saved"
            assert entry.vendor_id == vendor.id
            assert entry.category_id == cat_id
            assert entry.amount == 999.99

            start = datetime(2024, 3, 1, tzinfo=timezone.utc)
            end = datetime(2024, 3, 31, tzinfo=timezone.utc)
            report = generate_spend_report(start, end, session)

            assert len(report) == 1, f"Expected 1 report entry, got {len(report)}"
            assert report[0]["amount"] == 999.99
            assert report[0]["vendor_id"] == vendor.id
            assert report[0]["category_name"] == "Test Hardware"
            assert report[0]["date"] is not None

            start_out = datetime(2024, 4, 1, tzinfo=timezone.utc)
            end_out = datetime(2024, 4, 30, tzinfo=timezone.utc)
            empty_report = generate_spend_report(start_out, end_out, session)
            assert len(empty_report) == 0, "Should return empty list for out-of-range dates"

            try:
                generate_spend_report(end, start, session)
                assert False, "Should raise ValueError for inverted date range"
            except ValueError:
                pass

        engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("spend_tracking selftest OK")
