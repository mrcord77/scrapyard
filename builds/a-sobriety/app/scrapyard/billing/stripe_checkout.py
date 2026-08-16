"""
stripe_checkout — Create Stripe Checkout sessions for plans.

### PART-META-JSON
{
  "name": "stripe_checkout",
  "layer": "billing",
  "purpose": "Create Stripe Checkout sessions for plans.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "stripe"
  ],
  "inputs": "Public API: create_checkout_session(db, user_id, plan, *, success_url, cancel_url, price_id).",
  "outputs": "Returns: create_checkout_session -> dict.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `create_checkout_session` from `scrapyard.billing.stripe_checkout` and call it as shown in `example`; run `py -m scrapyard.billing.stripe_checkout` to see its offline selftest.",
  "example": "from scrapyard.billing.stripe_checkout import create_checkout_session",
  "import_path": "scrapyard.billing.stripe_checkout"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

def create_checkout_session(db, user_id: int, plan: str, *,
                            success_url: str, cancel_url: str, price_id: str | None = None) -> dict:
    """Create a checkout session and a local 'incomplete' subscription to reconcile
    against the webhook. Uses the real Stripe SDK when STRIPE_API_KEY is set;
    otherwise returns a deterministic local stub session so the flow is testable
    end-to-end without network."""
    import os
    from scrapyard.billing.subscriptions import SubscriptionService
    key = os.environ.get("STRIPE_API_KEY")
    external_id = None
    url = cancel_url
    if key:
        import stripe
        stripe.api_key = key
        sess = stripe.checkout.Session.create(
            mode="subscription", success_url=success_url, cancel_url=cancel_url,
            line_items=[{"price": price_id, "quantity": 1}],
            client_reference_id=str(user_id))
        external_id = sess["id"]; url = sess["url"]
    else:
        external_id = f"cs_local_{user_id}_{plan}"
        url = success_url + f"?session_id={external_id}"
    SubscriptionService(db).create(user_id, plan, external_id=external_id, status="incomplete")
    db.flush()
    return {"checkout_url": url, "external_id": external_id, "live": bool(key)}


def _selftest() -> None:
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import IntPKModel
    from scrapyard.billing.subscriptions import SubscriptionService

    saved_key = os.environ.pop("STRIPE_API_KEY", None)  # force offline stub path
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
            IntPKModel.metadata.create_all(engine)
            try:
                with Session(engine) as db:
                    out = create_checkout_session(
                        db, 7, "pro",
                        success_url="https://app.example/ok",
                        cancel_url="https://app.example/cancel")
                    assert out["live"] is False
                    assert out["external_id"] == "cs_local_7_pro"
                    assert out["checkout_url"].startswith("https://app.example/ok?session_id=cs_local_7_pro")

                    # a reconcilable local subscription was created
                    sub = SubscriptionService(db).by_external("cs_local_7_pro")
                    assert sub is not None
                    assert sub.user_id == 7 and sub.plan == "pro" and sub.status == "incomplete"
                    db.commit()
            finally:
                engine.dispose()
    finally:
        if saved_key is not None:
            os.environ["STRIPE_API_KEY"] = saved_key


if __name__ == "__main__":
    _selftest()
    print("stripe_checkout selftest OK")
