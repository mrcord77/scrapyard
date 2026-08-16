"""
stripe_webhooks — Verify + dispatch Stripe webhook events.

### PART-META-JSON
{
  "name": "stripe_webhooks",
  "layer": "billing",
  "purpose": "Verify + dispatch Stripe webhook events.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "stripe",
    "fastapi"
  ],
  "inputs": "Public API: verify_signature(payload, sig_header, secret, *, tolerance); sign_payload(payload, secret, ts); already_processed(db, event_id); handle_event(db, event, *, secret, payload, sig_header); ProcessedEvent(...); WebhookError(...).",
  "outputs": "Returns: verify_signature -> dict; sign_payload -> str; already_processed -> bool; handle_event -> dict.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `verify_signature` from `scrapyard.billing.stripe_webhooks` and call it as shown in `example`; run `py -m scrapyard.billing.stripe_webhooks` to see its offline selftest.",
  "example": "from scrapyard.billing.stripe_webhooks import verify_signature",
  "import_path": "scrapyard.billing.stripe_webhooks"
}
### END-PART-META
"""
from __future__ import annotations
import hashlib, hmac, json, time
from datetime import datetime
STATUS = "core"
from sqlalchemy import String, DateTime, func, select
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel


class ProcessedEvent(IntPKModel):
    """Idempotency ledger: every webhook event id is recorded once. Replays are
    detected and ignored (lesson L001)."""
    __tablename__ = "processed_webhook_events"
    event_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookError(ValueError):
    pass


def verify_signature(payload: bytes, sig_header: str, secret: str, *, tolerance: int = 300) -> dict:
    """Verify a Stripe-style signed payload (t=...,v1=...). Raises WebhookError on
    bad signature or stale timestamp. Returns the parsed event."""
    if not secret:
        raise WebhookError("webhook secret not configured")
    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    ts, v1 = parts.get("t"), parts.get("v1")
    if not ts or not v1:
        raise WebhookError("malformed signature header")
    if abs(time.time() - int(ts)) > tolerance:
        raise WebhookError("timestamp outside tolerance (possible replay)")
    signed = f"{ts}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, v1):
        raise WebhookError("signature mismatch")
    return json.loads(payload.decode())


def sign_payload(payload: bytes, secret: str, ts: int | None = None) -> str:
    """Helper to produce a valid signature header (used in tests and by senders)."""
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def already_processed(db, event_id: str) -> bool:
    return db.scalars(select(ProcessedEvent).where(ProcessedEvent.event_id == event_id)).first() is not None


def handle_event(db, event: dict, *, secret: str | None = None,
                 payload: bytes | None = None, sig_header: str | None = None) -> dict:
    """Process a webhook idempotently. If raw payload+signature are supplied they're
    verified first. Replayed event ids are acknowledged but not re-applied."""
    from scrapyard.billing.subscriptions import SubscriptionService
    from scrapyard.admin.audit_logs import record
    if payload is not None and sig_header is not None:
        event = verify_signature(payload, sig_header, secret or "")
    event_id = event.get("id")
    if not event_id:
        raise WebhookError("event missing id")
    if already_processed(db, event_id):
        return {"status": "duplicate_ignored", "event_id": event_id}
    db.add(ProcessedEvent(event_id=event_id))
    etype = event.get("type", "")
    data = event.get("data", {}).get("object", {})
    svc = SubscriptionService(db)
    result = {"status": "processed", "event_id": event_id, "type": etype}
    ext = data.get("subscription") or data.get("id") or data.get("client_reference_id")
    sub = svc.by_external(ext) if ext else None
    if etype in ("checkout.session.completed", "customer.subscription.created",
                 "invoice.payment_succeeded") and sub:
        svc.set_status(sub.id, "active")
        record(db, action="subscription_activated", actor_user_id=sub.user_id,
               target=f"subscription:{sub.id}", detail=etype)
    elif etype in ("customer.subscription.deleted", "customer.subscription.canceled") and sub:
        svc.set_status(sub.id, "canceled")
        record(db, action="subscription_canceled", actor_user_id=sub.user_id,
               target=f"subscription:{sub.id}", detail=etype)
    db.flush()
    return result


def _selftest() -> None:
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import IntPKModel
    from scrapyard.billing.subscriptions import SubscriptionService
    import scrapyard.admin.audit_logs  # noqa: F401 - registers audit_logs table for create_all

    secret = "whsec_test_secret"

    # --- signature verification (pure, offline) ---
    payload = json.dumps({"id": "evt_1", "type": "ping"}).encode()
    header = sign_payload(payload, secret)
    assert verify_signature(payload, header, secret)["id"] == "evt_1"

    for bad_call in [
        lambda: verify_signature(payload, header, "wrong_secret"),
        lambda: verify_signature(payload + b"x", header, secret),
        lambda: verify_signature(payload, "garbage", secret),
        lambda: verify_signature(payload, sign_payload(payload, secret, ts=int(time.time()) - 10_000), secret),
        lambda: verify_signature(payload, header, ""),
    ]:
        try:
            bad_call()
            assert False, "expected WebhookError"
        except WebhookError:
            pass

    # --- idempotent dispatch over sqlite ---
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                sub = SubscriptionService(db).create(1, "pro", external_id="sub_x")
                db.commit()

                event = {"id": "evt_act", "type": "invoice.payment_succeeded",
                         "data": {"object": {"subscription": "sub_x"}}}
                out = handle_event(db, event)
                assert out["status"] == "processed"
                assert SubscriptionService(db).by_external("sub_x").status == "active"

                # replay is acknowledged, not re-applied
                assert handle_event(db, event)["status"] == "duplicate_ignored"

                # cancellation path
                cancel_evt = {"id": "evt_del", "type": "customer.subscription.deleted",
                              "data": {"object": {"id": "sub_x"}}}
                assert handle_event(db, cancel_evt)["status"] == "processed"
                assert SubscriptionService(db).by_external("sub_x").status == "canceled"

                # verified ingest: raw payload + signature
                raw = json.dumps({"id": "evt_signed", "type": "ping", "data": {}}).encode()
                out = handle_event(db, {}, secret=secret, payload=raw, sig_header=sign_payload(raw, secret))
                assert out == {"status": "processed", "event_id": "evt_signed", "type": "ping"}

                # event without id is rejected
                try:
                    handle_event(db, {"type": "x"})
                    assert False
                except WebhookError:
                    pass
                db.commit()
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("stripe_webhooks selftest OK")
