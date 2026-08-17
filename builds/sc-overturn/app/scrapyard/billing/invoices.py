"""
invoices — Canonical accounts-receivable Invoice model + record/list/query API.

### PART-META-JSON
{
  "name": "invoices",
  "layer": "billing",
  "purpose": "Own the canonical AR Invoice model (table 'invoices_invoices', integer amount_cents) and the record/mark-paid/list/summary API; sibling billing parts (invoice_reporting, invoice_lifecycle, invoice_notifications, dunning) import this model instead of redefining it.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "record_invoice(db, user_id, amount_cents, ...); mark_paid(db, invoice_id); list_invoices(db, filters); fetch_invoice_by_external_id(db, external_id); validate_invoice_data(amount_cents, currency).",
  "outputs": "Invoice rows (status open|paid|void), serialized dicts, per-user summaries. NOTE: this is the ACCOUNTS-RECEIVABLE invoice (what customers owe us); vendor bills payable live in procurement_vend/invoice_matching's AP Invoice - same word, different ledger, deliberately distinct tables.",
  "files_created": [],
  "security_notes": "Money-touching part. Amounts are integer cents end-to-end (no float drift); validate_invoice_data enforces positive integer amounts and a currency whitelist. Post-record hooks are exception-isolated so a bad hook cannot corrupt the billing path. Risks: record_invoice itself does NOT call validate_invoice_data (callers like create_invoice_from_subscription do) - validate before recording external input; external_id is not unique-constrained, so idempotent ingestion from a payment provider must dedupe on external_id before insert.",
  "ai_usage": "Import Invoice and the API from `scrapyard.billing.invoices`; auxiliary per-domain invoice attributes belong in the sibling parts' aux tables keyed by Invoice.id.",
  "example": "from scrapyard.billing.invoices import Invoice, record_invoice",
  "import_path": "scrapyard.billing.invoices"
}
### END-PART-META
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List

from sqlalchemy import DateTime, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

STATUS = "core"

import logging

log = logging.getLogger("scrapyard.billing.invoices")

VALID_CURRENCIES = ("usd", "eur")


class InvoiceNotFoundError(Exception):
    pass


class Invoice(IntPKModel):
    __tablename__ = "invoices_invoices"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    subscription_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="usd")
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|paid|void
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# -- hooks (called after an invoice is recorded or changes status) -------------
_HOOKS: List[Callable[[Invoice], None]] = []


def add_invoice_hook(hook: Callable[[Invoice], None]) -> None:
    """Register a callback fired after record_invoice/mark_paid. Exceptions in
    hooks are logged, never raised into the billing path."""
    _HOOKS.append(hook)


def _fire_hooks(inv: Invoice) -> None:
    for h in _HOOKS:
        try:
            h(inv)
        except Exception:  # noqa: BLE001 - a hook must never break billing
            log.exception("invoice hook %r failed for invoice %s", h, inv.id)


# -- original core API ----------------------------------------------------------
def record_invoice(db, user_id, amount_cents, *, subscription_id=None, currency="usd",
                   status="open", external_id=None) -> Invoice:
    inv = Invoice(user_id=user_id, subscription_id=subscription_id, amount_cents=amount_cents,
                  currency=currency, status=status, external_id=external_id)
    db.add(inv)
    db.flush()
    _fire_hooks(inv)
    return inv


def mark_paid(db, invoice_id: int) -> Invoice | None:
    inv = db.get(Invoice, invoice_id)
    if inv:
        inv.status = "paid"
        db.flush()
        _fire_hooks(inv)
    return inv


def for_user(db, user_id: int):
    return list(db.scalars(select(Invoice).where(Invoice.user_id == user_id)
                           .order_by(Invoice.created_at.desc())))


# -- extended service API --------------------------------------------------------
def fetch_invoice_by_external_id(db: Session, external_id: str) -> Invoice:
    inv = db.scalars(
        select(Invoice).where(Invoice.external_id == external_id)
    ).first()
    if inv is None:
        raise InvoiceNotFoundError(f"Invoice with external ID {external_id} not found")
    return inv


def list_invoices(
    db: Session,
    user_id: int | None = None,
    status: str | None = None,
    currency: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Invoice]:
    query = select(Invoice)
    if user_id is not None:
        query = query.where(Invoice.user_id == user_id)
    if status is not None:
        query = query.where(Invoice.status == status)
    if currency is not None:
        query = query.where(Invoice.currency == currency)
    query = query.order_by(Invoice.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(query))


def archive_invoice(db: Session, invoice_id: int) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise InvoiceNotFoundError(f"Invoice with ID {invoice_id} not found")
    inv.deleted_at = datetime.now(timezone.utc)
    db.flush()
    return inv


def bulk_mark_paid(db: Session, invoice_ids: List[int]) -> List[Invoice]:
    """Mark many invoices paid; unknown ids are logged and skipped, the rest
    proceed (idempotent for already-paid rows)."""
    out: List[Invoice] = []
    for invoice_id in invoice_ids:
        inv = db.get(Invoice, invoice_id)
        if not inv:
            log.warning("bulk_mark_paid: invoice %s not found, skipped", invoice_id)
            continue
        inv.status = "paid"
        _fire_hooks(inv)
        out.append(inv)
    db.flush()
    return out


def create_invoice_from_subscription(
    db: Session,
    subscription_id: int,
    amount_cents: int,
    currency: str = "usd",
) -> Invoice:
    from scrapyard.billing.subscriptions import Subscription

    validate_invoice_data(amount_cents, currency)
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        raise InvoiceNotFoundError(f"Subscription {subscription_id} not found")
    return record_invoice(
        db, sub.user_id, amount_cents,
        subscription_id=subscription_id, currency=currency,
    )


def get_invoice_summary(db: Session, user_id: int) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "total_open": 0, "total_paid": 0, "total_void": 0,
        "usd_total": 0.0, "eur_total": 0.0,
    }
    for inv in db.scalars(select(Invoice).where(Invoice.user_id == user_id)):
        key = f"total_{inv.status.lower()}"
        if key in summary:
            summary[key] += 1
        cur_key = f"{inv.currency}_total"
        if cur_key in summary:
            summary[cur_key] += inv.amount_cents / 100
    return summary


def serialize_invoice(inv: Invoice, include_deleted: bool = False) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": inv.id,
        "user_id": inv.user_id,
        "subscription_id": inv.subscription_id,
        "amount_cents": inv.amount_cents,
        "currency": inv.currency,
        "status": inv.status,
        "external_id": inv.external_id,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }
    if include_deleted:
        data["deleted_at"] = inv.deleted_at.isoformat() if inv.deleted_at else None
    return data


def validate_invoice_data(amount_cents: int, currency: str) -> None:
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        raise ValueError("Amount must be a positive integer of cents")
    if currency not in VALID_CURRENCIES:
        raise ValueError(f"Currency must be one of {VALID_CURRENCIES}")


def apply_policy(policy: str, invoice: Invoice, now: datetime | None = None) -> bool:
    """Evaluate a named housekeeping policy against an invoice."""
    now = now or datetime.now(timezone.utc)

    def _auto_archive(inv: Invoice) -> bool:
        created = inv.created_at
        if created is None:
            return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return now - created > timedelta(days=30)

    policies: Dict[str, Callable[[Invoice], bool]] = {
        "auto_archive_after_30_days": _auto_archive,
    }
    return policies.get(policy, lambda _inv: False)(invoice)


def _selftest() -> None:
    import tempfile, os
    from sqlalchemy import create_engine
    from scrapyard.database.base_model import IntPKModel

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        log.setLevel(logging.CRITICAL)  # the deliberate bad-hook test logs exceptions
        try:
            with Session(engine) as db:
                # record + hooks
                fired: list[int] = []
                add_invoice_hook(lambda inv: fired.append(inv.id))
                # a hook that raises must never break the billing path
                add_invoice_hook(lambda inv: (_ for _ in ()).throw(RuntimeError("boom")))
                inv = record_invoice(db, user_id=1, amount_cents=10000, external_id="ext-1")
                db.commit()
                assert inv.id in fired
                assert inv.status == "open"

                # mark_paid + fetch by external id
                assert mark_paid(db, inv.id).status == "paid"
                assert fetch_invoice_by_external_id(db, "ext-1").id == inv.id
                try:
                    fetch_invoice_by_external_id(db, "missing")
                    assert False
                except InvoiceNotFoundError:
                    pass

                # list/filter
                inv2 = record_invoice(db, user_id=1, amount_cents=5000, currency="eur")
                db.commit()
                assert [i.id for i in list_invoices(db, user_id=1, status="paid")] == [inv.id]
                assert [i.id for i in list_invoices(db, currency="eur")] == [inv2.id]
                assert len(for_user(db, 1)) == 2

                # bulk_mark_paid skips unknown ids
                out = bulk_mark_paid(db, [inv2.id, 99999])
                assert [i.id for i in out] == [inv2.id]

                # summary
                s = get_invoice_summary(db, 1)
                assert s["total_paid"] == 2 and s["usd_total"] == 100.0 and s["eur_total"] == 50.0

                # archive + serialize
                arch = archive_invoice(db, inv.id)
                assert arch.deleted_at is not None
                data = serialize_invoice(arch, include_deleted=True)
                assert data["amount_cents"] == 10000 and data["deleted_at"]

                # validation
                for bad in [(0, "usd"), (-5, "usd"), (100, "gbp"), (1.5, "usd")]:
                    try:
                        validate_invoice_data(*bad)
                        assert False, f"should reject {bad}"
                    except ValueError:
                        pass
                validate_invoice_data(100, "usd")

                # policy
                old = Invoice(user_id=1, amount_cents=1,
                              created_at=datetime.now(timezone.utc) - timedelta(days=45))
                assert apply_policy("auto_archive_after_30_days", old) is True
                assert apply_policy("auto_archive_after_30_days", inv2) is False
                assert apply_policy("unknown_policy", inv2) is False
        finally:
            _HOOKS.clear()
            log.setLevel(logging.NOTSET)
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("invoices selftest OK")
