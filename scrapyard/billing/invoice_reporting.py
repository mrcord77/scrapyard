"""
invoice_reporting — Receivables reports over the canonical billing Invoice model.

### PART-META-JSON
{
  "name": "invoice_reporting",
  "layer": "billing",
  "purpose": "Generate invoice reports and receivables summaries from the canonical billing/invoices Invoice model plus a reporting-details auxiliary table (customer name, due date).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure(engine); generate_invoice_report(start_date, end_date); generate_receivables_summary().",
  "outputs": "ReportRow / Summary dataclasses. Uses scrapyard.billing.invoices.Invoice (canonical, AR side) joined to InvoiceReportingDetail ('invoice_reporting_details').",
  "files_created": [],
  "security_notes": "Read-only over billing data: no mutation paths. Amounts are converted from the canonical integer amount_cents to float only for report presentation - do not feed ReportRow.amount back into ledgers. Customer names/emails in report rows are PII; callers must not log full report rows at info level.",
  "ai_usage": "Import from `scrapyard.billing.invoice_reporting`; call configure(engine) first; the Invoice model itself is owned by scrapyard.billing.invoices.",
  "example": "from scrapyard.billing.invoice_reporting import generate_receivables_summary",
  "import_path": "scrapyard.billing.invoice_reporting"
}
### END-PART-META
"""
from sqlalchemy import create_engine, func, select, String, DateTime
from sqlalchemy.orm import Session, sessionmaker, Mapped, mapped_column
from sqlalchemy import ForeignKey
from scrapyard.database.base_model import IntPKModel
from scrapyard.billing.invoices import Invoice, record_invoice, mark_paid
from datetime import date, datetime
from dataclasses import dataclass
from typing import List, Optional, Callable, Any
import os, logging, tempfile

logger = logging.getLogger(__name__)

STATUS = "core"


@dataclass
class ReportRow:
    invoice_id: int
    customer_name: str
    amount: float
    payment_status: str
    due_date: Optional[datetime]


@dataclass
class Summary:
    total_receivables: float
    outstanding_amount: float


class InvoiceReportingDetail(IntPKModel):
    """Reporting-only attributes for a canonical invoice (name, due date)."""
    __tablename__ = "invoice_reporting_details"

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices_invoices.id"), index=True, nullable=False
    )
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


_engine: Optional[Any] = None
_session_maker: Optional[Callable[[], Session]] = None


def configure(engine: Any) -> None:
    """Configure the module with a SQLAlchemy engine."""
    global _engine, _session_maker
    _engine = engine
    _session_maker = sessionmaker(bind=engine)


def _get_session() -> Session:
    if _session_maker is None:
        raise RuntimeError("invoice_reporting has no configured database session.")
    return _session_maker()


def _as_date(value: date) -> date:
    """Normalize a datetime (which is a subclass of date) to a date."""
    if isinstance(value, datetime):
        return value.date()
    return value


def _display_status(status: str) -> str:
    return {"open": "Unpaid", "paid": "Paid", "void": "Void"}.get(status, status)


def generate_invoice_report(start_date: date, end_date: date) -> List[ReportRow]:
    """Unpaid invoices created within [start_date, end_date], with reporting details."""
    session = _get_session()
    try:
        start = _as_date(start_date)
        end = _as_date(end_date)

        stmt = (
            select(
                Invoice.id.label("invoice_id"),
                func.coalesce(InvoiceReportingDetail.customer_name, "Unknown Customer").label("customer_name"),
                Invoice.amount_cents.label("amount_cents"),
                Invoice.status.label("status"),
                InvoiceReportingDetail.due_date.label("due_date"),
            )
            .join(InvoiceReportingDetail, InvoiceReportingDetail.invoice_id == Invoice.id, isouter=True)
            .where(
                func.date(Invoice.created_at).between(start, end),
                Invoice.status != "paid",
            )
        )

        rows = session.execute(stmt).mappings().all()
        return [
            ReportRow(
                invoice_id=row["invoice_id"],
                customer_name=row["customer_name"],
                amount=row["amount_cents"] / 100.0,
                payment_status=_display_status(row["status"]),
                due_date=row["due_date"],
            )
            for row in rows
        ]
    finally:
        session.close()


def generate_receivables_summary() -> Summary:
    session = _get_session()
    try:
        total_stmt = select(func.coalesce(func.sum(Invoice.amount_cents), 0))
        total_cents = session.execute(total_stmt).scalar_one()

        outstanding_stmt = select(func.coalesce(func.sum(Invoice.amount_cents), 0)).where(
            Invoice.status == "open"
        )
        outstanding_cents = session.execute(outstanding_stmt).scalar_one()

        return Summary(
            total_receivables=total_cents / 100.0,
            outstanding_amount=outstanding_cents / 100.0,
        )
    finally:
        session.close()


def _selftest():
    global _engine, _session_maker

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)

        try:
            IntPKModel.metadata.create_all(engine)
            configure(engine)

            with Session(engine) as session:
                inv_a = record_invoice(session, user_id=1, amount_cents=10000)
                inv_b = record_invoice(session, user_id=2, amount_cents=20000)
                inv_c = record_invoice(session, user_id=3, amount_cents=15000)
                session.flush()
                mark_paid(session, inv_b.id)
                session.add_all([
                    InvoiceReportingDetail(invoice_id=inv_a.id, customer_name="Customer A",
                                           due_date=datetime(2023, 1, 15)),
                    InvoiceReportingDetail(invoice_id=inv_b.id, customer_name="Customer B",
                                           due_date=datetime(2023, 1, 15)),
                    InvoiceReportingDetail(invoice_id=inv_c.id, customer_name="Customer C",
                                           due_date=datetime(2023, 1, 30)),
                ])
                session.commit()
                ids = (inv_a.id, inv_b.id, inv_c.id)

            # created_at is set server-side (UTC); use a +/-1 day window so the
            # test is immune to local-vs-UTC date rollover.
            from datetime import timedelta, timezone
            today = datetime.now(timezone.utc).date()
            report_rows = generate_invoice_report(today - timedelta(days=1), today + timedelta(days=1))
            # inv_b is paid, so only the two open invoices appear
            assert {r.invoice_id for r in report_rows} == {ids[0], ids[2]}
            by_id = {r.invoice_id: r for r in report_rows}
            assert by_id[ids[0]].customer_name == "Customer A"
            assert by_id[ids[0]].amount == 100.0
            assert by_id[ids[0]].payment_status == "Unpaid"
            assert by_id[ids[0]].due_date == datetime(2023, 1, 15)

            # Window that excludes everything
            assert generate_invoice_report(date(2000, 1, 1), date(2000, 1, 2)) == []

            summary = generate_receivables_summary()
            assert summary.total_receivables == 450.0
            assert summary.outstanding_amount == 250.0

            logger.info("Self-test passed successfully.")
        finally:
            _engine = None
            _session_maker = None
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("invoice_reporting selftest OK")
