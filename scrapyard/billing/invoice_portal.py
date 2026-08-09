"""
invoice_portal — Stripe billing portal session creation.

### PART-META-JSON
{
  "name": "invoice_portal",
  "layer": "billing",
  "purpose": "Stripe billing portal session creation.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "stripe"
  ],
  "inputs": "Public API: portal_link(db, user_id, *, return_url).",
  "outputs": "Returns: portal_link -> dict.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `portal_link` from `scrapyard.billing.invoice_portal` and call it as shown in `example`; run `py -m scrapyard.billing.invoice_portal` to see its offline selftest.",
  "example": "from scrapyard.billing.invoice_portal import portal_link",
  "import_path": "scrapyard.billing.invoice_portal"
}
### END-PART-META
"""
from __future__ import annotations

STATUS = "core"

def portal_link(db, user_id: int, *, return_url: str = "/") -> dict:
    """Return a customer billing-portal link. Uses Stripe's billing portal when
    configured; otherwise returns a local invoices summary so the UX is testable."""
    import os
    from scrapyard.billing.invoices import for_user
    key = os.environ.get("STRIPE_API_KEY")
    if key:
        import stripe
        stripe.api_key = key
        sub = None
        from scrapyard.billing.subscriptions import SubscriptionService
        sub = SubscriptionService(db).for_user(user_id)
        if sub and sub.external_id:
            sess = stripe.billing_portal.Session.create(customer=sub.external_id, return_url=return_url)
            return {"portal_url": sess["url"], "live": True}
    invoices = [{"id": i.id, "amount_cents": i.amount_cents, "status": i.status} for i in for_user(db, user_id)]
    return {"portal_url": None, "invoices": invoices, "live": False}


def _selftest() -> None:
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import IntPKModel
    from scrapyard.billing.invoices import record_invoice

    # Force the offline path regardless of the environment
    saved_key = os.environ.pop("STRIPE_API_KEY", None)
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
            IntPKModel.metadata.create_all(engine)
            try:
                with Session(engine) as db:
                    inv = record_invoice(db, user_id=1, amount_cents=2500)
                    db.commit()

                    out = portal_link(db, 1)
                    assert out["live"] is False and out["portal_url"] is None
                    assert out["invoices"] == [{"id": inv.id, "amount_cents": 2500, "status": "open"}]

                    empty = portal_link(db, 42)
                    assert empty["invoices"] == [] and empty["live"] is False
            finally:
                engine.dispose()
    finally:
        if saved_key is not None:
            os.environ["STRIPE_API_KEY"] = saved_key


if __name__ == "__main__":
    _selftest()
    print("invoice_portal selftest OK")
