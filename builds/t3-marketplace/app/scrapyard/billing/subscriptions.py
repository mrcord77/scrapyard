"""
subscriptions — Subscription model + lifecycle state.

### PART-META-JSON
{
  "name": "subscriptions",
  "layer": "billing",
  "purpose": "Subscription model + lifecycle state.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: Subscription(...); SubscriptionService(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `Subscription` from `scrapyard.billing.subscriptions` and call it as shown in `example`; run `py -m scrapyard.billing.subscriptions` to see its offline selftest.",
  "example": "from scrapyard.billing.subscriptions import Subscription",
  "import_path": "scrapyard.billing.subscriptions"
}
### END-PART-META
"""
from __future__ import annotations
from datetime import datetime
STATUS = "core"
from sqlalchemy import String, Integer, DateTime, func, select
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel

# canonical lifecycle states
STATES = ("incomplete", "active", "past_due", "canceled", "trialing")

class Subscription(IntPKModel):
    __tablename__ = "subscriptions"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    plan: Mapped[str] = mapped_column(String(50), default="free")
    status: Mapped[str] = mapped_column(String(20), default="incomplete")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class SubscriptionService:
    def __init__(self, db):
        self.db = db
    def create(self, user_id: int, plan: str, *, external_id: str | None = None, status: str = "incomplete"):
        sub = Subscription(user_id=user_id, plan=plan, status=status, external_id=external_id)
        self.db.add(sub); self.db.flush(); return sub
    def for_user(self, user_id: int):
        return self.db.scalars(select(Subscription).where(Subscription.user_id == user_id)
                               .order_by(Subscription.created_at.desc())).first()
    def by_external(self, external_id: str):
        return self.db.scalars(select(Subscription).where(Subscription.external_id == external_id)).first()
    def set_status(self, sub_id: int, status: str):
        if status not in STATES:
            raise ValueError(f"invalid status: {status}")
        sub = self.db.get(Subscription, sub_id)
        if sub: sub.status = status; self.db.flush()
        return sub


def _selftest() -> None:
    import tempfile, os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                svc = SubscriptionService(db)
                sub = svc.create(1, "pro", external_id="sub_ext_1")
                assert sub.id is not None and sub.status == "incomplete"

                assert svc.for_user(1).id == sub.id
                assert svc.for_user(999) is None
                assert svc.by_external("sub_ext_1").id == sub.id
                assert svc.by_external("nope") is None

                assert svc.set_status(sub.id, "active").status == "active"
                assert svc.set_status(999999, "active") is None
                try:
                    svc.set_status(sub.id, "bogus")
                    assert False, "invalid status must raise"
                except ValueError:
                    pass
                db.commit()
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("subscriptions selftest OK")
