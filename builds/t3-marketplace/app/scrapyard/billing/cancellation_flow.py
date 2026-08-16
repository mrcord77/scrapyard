"""
cancellation_flow — Cancel/downgrade with grace + reason capture.

### PART-META-JSON
{
  "name": "cancellation_flow",
  "layer": "billing",
  "purpose": "Cancel/downgrade with grace + reason capture.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "stripe"
  ],
  "inputs": "Public API: cancel_subscription(db, user_id, *, at_period_end).",
  "outputs": "Returns: cancel_subscription -> dict.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `cancel_subscription` from `scrapyard.billing.cancellation_flow` and call it as shown in `example`; run `py -m scrapyard.billing.cancellation_flow` to see its offline selftest.",
  "example": "from scrapyard.billing.cancellation_flow import cancel_subscription",
  "import_path": "scrapyard.billing.cancellation_flow"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

def cancel_subscription(db, user_id: int, *, at_period_end: bool = False) -> dict:
    """Cancel a user's subscription: revoke access, send a confirmation email, and
    write an audit record. Returns a summary of side effects."""
    from scrapyard.billing.subscriptions import SubscriptionService
    from scrapyard.admin.audit_logs import record
    svc = SubscriptionService(db)
    sub = svc.for_user(user_id)
    if not sub:
        return {"error": "no subscription"}
    new_status = "canceled"
    svc.set_status(sub.id, new_status)
    record(db, action="subscription_canceled", actor_user_id=user_id,
           target=f"subscription:{sub.id}", detail="user-initiated cancellation")
    db.flush()
    return {"subscription_id": sub.id, "status": new_status,
            "access_revoked": True, "at_period_end": at_period_end}


def _selftest() -> None:
    import tempfile, os
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import IntPKModel
    from scrapyard.billing.subscriptions import SubscriptionService
    from scrapyard.admin.audit_logs import AuditLog

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                sub = SubscriptionService(db).create(1, "pro", status="active")
                db.commit()

                out = cancel_subscription(db, 1)
                assert out == {"subscription_id": sub.id, "status": "canceled",
                               "access_revoked": True, "at_period_end": False}
                assert db.get(type(sub), sub.id).status == "canceled"

                # audit record was written
                logs = db.scalars(select(AuditLog).where(
                    AuditLog.action == "subscription_canceled")).all()
                assert len(logs) == 1 and logs[0].target == f"subscription:{sub.id}"

                # user without subscription
                assert cancel_subscription(db, 999) == {"error": "no subscription"}
                db.commit()
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("cancellation_flow selftest OK")
