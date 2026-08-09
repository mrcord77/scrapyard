"""
refund_processor — Initiate and cancel refunds against charges with an over-refund guard.

### PART-META-JSON
{
  "name": "refund_processor",
  "layer": "payments_reconci",
  "purpose": "Create refunds against stored charges, enforcing that cumulative non-canceled refunds never exceed the charge amount; support cancellation of initiated refunds.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "set_engine(engine); initiate_refund(charge_id, amount); cancel_refund(refund_id). Amounts are currency units (dollars) with at most 2 decimal places.",
  "outputs": "Refund rows (status initiated|canceled) detached from the session; ValueError on invalid/over-limit operations.",
  "files_created": [],
  "security_notes": "Money-touching part. OVER-REFUND GUARD: initiate_refund sums all existing non-canceled refunds for the charge and rejects any request that would push the total past the charge amount; the check and insert run inside one transaction so a failed request writes nothing. Sub-cent amounts are rejected (max 2 decimal places) and ALL money comparisons are done in integer cents (round-half-away conversions) - no float-epsilon guard. Precision note: the schema stores Float currency units for API compatibility; exact 2dp values round-trip exactly through IEEE754 at these magnitudes, and every guard re-derives integer cents before comparing, so drift cannot accumulate into the guard. Residual risks: no idempotency key (a retried initiate_refund double-refunds up to the guard limit) and cancel/initiate race on two concurrent sessions is serialized only by the DB transaction.",
  "ai_usage": "Import from `scrapyard.payments_reconci.refund_processor`; call set_engine() first; treat ValueError as a policy rejection, not a transport error.",
  "example": "from scrapyard.payments_reconci.refund_processor import initiate_refund",
  "import_path": "scrapyard.payments_reconci.refund_processor"
}
### END-PART-META
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone

from sqlalchemy import create_engine, ForeignKey, String, Float, DateTime, select, func
from sqlalchemy.orm import Session, Mapped, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

STATUS = "core"

_engine = None


def _to_cents(amount: float, *, what: str = "amount") -> int:
    """Convert a currency amount to integer cents, rejecting sub-cent values.

    All money comparisons in this module go through integer cents so that no
    float-epsilon tolerance is ever needed.
    """
    cents = round(float(amount) * 100)
    if abs(float(amount) * 100 - cents) > 1e-6:
        raise ValueError(f"{what} {amount!r} has sub-cent precision; max 2 decimal places allowed.")
    return int(cents)


class Charge(IntPKModel):
    __tablename__ = "charge"
    amount: Mapped[float] = mapped_column(Float, nullable=False)


class Refund(IntPKModel):
    __tablename__ = "refund"
    charge_id: Mapped[int] = mapped_column(ForeignKey("charge.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="initiated", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


def set_engine(engine) -> None:
    global _engine
    _engine = engine


def _current_session() -> Session:
    if _engine is None:
        raise RuntimeError("No database engine configured. Call set_engine() first.")
    return Session(_engine)


def initiate_refund(charge_id, amount: float) -> Refund:
    if amount <= 0:
        raise ValueError("Refund amount must be positive.")
    amount_cents = _to_cents(amount, what="Refund amount")

    session = _current_session()
    try:
        with session.begin():
            charge = session.get(Charge, charge_id)
            if charge is None:
                raise ValueError(f"Charge {charge_id!r} does not exist.")

            existing = session.scalars(
                select(Refund.amount).where(
                    Refund.charge_id == charge_id,
                    Refund.status != "canceled",
                )
            ).all()
            # Over-refund guard: exact integer-cents comparison, no epsilon.
            total_existing_cents = sum(_to_cents(a, what="Stored refund amount") for a in existing)

            if total_existing_cents + amount_cents > _to_cents(charge.amount, what="Charge amount"):
                raise ValueError(
                    f"Refund amount {amount} exceeds remaining charge balance."
                )

            refund = Refund(
                charge_id=charge_id,
                amount=amount,
                status="initiated",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(refund)

        session.refresh(refund)
        session.expunge(refund)
        return refund
    finally:
        session.close()


def cancel_refund(refund_id) -> Refund:
    session = _current_session()
    try:
        with session.begin():
            refund = session.get(Refund, refund_id)
            if refund is None:
                raise ValueError(f"Refund {refund_id!r} does not exist.")
            if refund.status != "initiated":
                raise ValueError(
                    f"Cannot cancel refund in '{refund.status}' status."
                )
            refund.status = "canceled"
            refund.updated_at = datetime.now(timezone.utc)

        session.refresh(refund)
        session.expunge(refund)
        return refund
    finally:
        session.close()


def _selftest() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = f"sqlite:///{tmpdir}/test_refunds.db"
        engine = create_engine(db_path, echo=False, future=True)
        set_engine(engine)

        try:
            IntPKModel.metadata.create_all(engine)

            # Seed charges
            with Session(engine) as session:
                charge_a = Charge(amount=100.0)
                charge_b = Charge(amount=50.0)
                session.add_all([charge_a, charge_b])
                session.commit()
                charge_a_id = charge_a.id
                charge_b_id = charge_b.id

            # Initiate refund for valid charge
            refund1 = initiate_refund(charge_a_id, 30.0)
            assert refund1.status == "initiated"
            assert refund1.amount == 30.0
            assert refund1.charge_id == charge_a_id
            assert refund1.id is not None
            assert isinstance(refund1.created_at, datetime)

            # Partial refund: additional refund within remaining balance
            refund2 = initiate_refund(charge_a_id, 70.0)
            assert refund2.status == "initiated"
            assert refund2.amount == 70.0

            # Refund amount must not exceed charge amount
            try:
                initiate_refund(charge_a_id, 1.0)
                assert False, "Expected over-refund to raise"
            except ValueError:
                pass

            # Refund amount > charge amount on fresh charge
            try:
                initiate_refund(charge_b_id, 60.0)
                assert False, "Expected excessive refund to raise"
            except ValueError:
                pass

            # Cancel refund before processing
            canceled = cancel_refund(refund2.id)
            assert canceled.status == "canceled"
            assert canceled.updated_at >= canceled.created_at

            # Canceling an already-canceled refund fails
            try:
                cancel_refund(refund2.id)
                assert False, "Expected double-cancel to raise"
            except ValueError:
                pass

            # Canceling a nonexistent refund fails
            try:
                cancel_refund(999999)
                assert False, "Expected missing refund cancel to raise"
            except ValueError:
                pass

            # Exact-cents accounting: 33.33 + 33.33 + 33.34 refunds a 100.00
            # charge to the cent with no epsilon slack, then 0.01 more fails.
            with Session(engine) as session:
                charge_c = Charge(amount=100.0)
                session.add(charge_c)
                session.commit()
                charge_c_id = charge_c.id
            for part_amount in (33.33, 33.33, 33.34):
                initiate_refund(charge_c_id, part_amount)
            try:
                initiate_refund(charge_c_id, 0.01)
                assert False, "Expected exact-limit over-refund to raise"
            except ValueError:
                pass

            # Sub-cent precision is rejected outright
            try:
                initiate_refund(charge_b_id, 0.001)
                assert False, "Expected sub-cent refund to raise"
            except ValueError as e:
                assert "sub-cent" in str(e)

            # Database records reflect operations
            with Session(engine) as session:
                refunds = session.scalars(
                    select(Refund).where(Refund.charge_id == charge_a_id)
                ).all()
                assert len(refunds) == 2
                statuses = {r.status for r in refunds}
                assert statuses == {"initiated", "canceled"}

                charge_a_record = session.get(Charge, charge_a_id)
                charge_b_record = session.get(Charge, charge_b_id)
                assert charge_a_record.amount == 100.0
                assert charge_b_record.amount == 50.0

            # No side effects on unrelated charge
            with Session(engine) as session:
                unrelated_refunds = session.scalar(
                    select(func.count(Refund.id)).where(
                        Refund.charge_id == charge_b_id
                    )
                )
                assert unrelated_refunds == 0

        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("refund_processor selftest OK")
