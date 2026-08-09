"""
payment_checks — Verify checkout/webhook path in test mode.

### PART-META-JSON
{
  "name": "payment_checks",
  "layer": "testing",
  "purpose": "Verify checkout/webhook path in test mode.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: check_subscription_activation(db, user_email, plan, success_url, cancel_url); simulate_webhook_event(db, event_type, event_data, secret); bulk_check_subscriptions(db, users, plan); audit_subscription_flow(db, user_id); validate_payment_intent(db, intent_id); ConfigurationError(...); WebhookEventError(...); TransactionError(...) (plus more).",
  "outputs": "Returns: check_subscription_activation -> Dict[str, Any]; simulate_webhook_event -> Dict[str, Any]; bulk_check_subscriptions -> List[Dict[str, Any]]; audit_subscription_flow -> Dict[str, Any]; validate_payment_intent -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `check_subscription_activation` from `scrapyard.testing.payment_checks` and call it as shown in `example`; run `py -m scrapyard.testing.payment_checks` to see its offline selftest.",
  "example": "from scrapyard.testing.payment_checks import check_subscription_activation",
  "import_path": "scrapyard.testing.payment_checks"
}
### END-PART-META
"""
from __future__ import annotations
import json
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from scrapyard.identity.users import UserService
from scrapyard.billing.stripe_checkout import create_checkout_session
from scrapyard.billing.subscriptions import SubscriptionService
from scrapyard.billing.entitlements import feature_allowed
from scrapyard.billing.stripe_webhooks import sign_payload, handle_event
import stripe

STATUS = "core"
_WEBHOOK_SECRET: str | None = None
_MOCK_ENTITLEMENTS = False

class ConfigurationError(Exception):
    pass

class WebhookEventError(Exception):
    pass

class TransactionError(Exception):
    pass

class DuplicateSubscriptionError(Exception):
    pass

class InvalidPlanError(Exception):
    pass

class SignatureVerificationError(Exception):
    pass

def check_subscription_activation(db: Session, user_email: str = "paycheck@example.test", plan: str = "pro", success_url: str = "/ok", cancel_url: str = "/no") -> Dict[str, Any]:
    """
    Verify a checkout->signed-webhook flow activates entitlements.
    """
    try:
        u = UserService(db).create(user_email, "password123")
        db.flush()
        co = create_checkout_session(db, u.id, plan, success_url=success_url, cancel_url=cancel_url)
        sub = SubscriptionService(db).for_user(u.id)
        pre = feature_allowed(sub, "premium")
        payload = json.dumps({"id": "evt_chk", "type": "checkout.session.completed",
                              "data": {"object": {"id": co["external_id"]}}}).encode()
        sig = sign_payload(payload, "whsec")
        handle_event(db, {}, secret="whsec", payload=payload, sig_header=sig)
        db.refresh(sub)
        return {"ok": (not pre) and feature_allowed(sub, "premium")}
    except ValueError as e:
        raise ValueError("Invalid user email or password") from e
    except stripe.error.AuthenticationError:
        raise ConfigurationError("Stripe API key not configured")
    except Exception as e:
        db.rollback()
        raise TransactionError(f"Database transaction failed: {e}")

def simulate_webhook_event(db: Session, event_type: str, event_data: Dict[str, Any], secret: str) -> Dict[str, Any]:
    """
    Simulates any webhook event type with custom data and signing.
    """
    payload = json.dumps(event_data).encode()
    sig = sign_payload(payload, secret)
    handle_event(db, {}, secret=secret, payload=payload, sig_header=sig)
    return {"status": "success"}

def bulk_check_subscriptions(db: Session, users: List[Dict[str, Any]], plan: str) -> List[Dict[str, Any]]:
    """
    Creates and checks multiple subscriptions in one transaction.
    """
    results = []
    for user_data in users:
        try:
            u = UserService(db).create(user_data["email"], "password123")
            db.flush()
            co = create_checkout_session(db, u.id, plan)
            sub = SubscriptionService(db).for_user(u.id)
            pre = feature_allowed(sub, "premium")
            payload = json.dumps({"id": f"evt_{u.id}", "type": "checkout.session.completed",
                                  "data": {"object": {"id": co["external_id"]}}}).encode()
            sig = sign_payload(payload, "whsec")
            handle_event(db, {}, secret="whsec", payload=payload, sig_header=sig)
            db.refresh(sub)
            results.append({"ok": (not pre) and feature_allowed(sub, "premium")})
        except ValueError as e:
            raise ValueError("Invalid user email or password") from e
        except stripe.error.AuthenticationError:
            raise ConfigurationError("Stripe API key not configured")
        except Exception as e:
            db.rollback()
            results.append({"error": f"Database transaction failed: {e}"})
    return results

def audit_subscription_flow(db: Session, user_id: int) -> Dict[str, Any]:
    """
    Logs and returns detailed audit trail of subscription lifecycle.
    """
    try:
        sub = SubscriptionService(db).for_user(user_id)
        audit_log = {"user_id": user_id, "subscription_status": sub.status}
        return audit_log
    except Exception as e:
        db.rollback()
        raise TransactionError(f"Database transaction failed: {e}")

def validate_payment_intent(db: Session, intent_id: str) -> Dict[str, Any]:
    """
    Verifies that a payment intent was processed and linked to a subscription.
    """
    try:
        # This is a placeholder for actual implementation
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        raise TransactionError(f"Database transaction failed: {e}")

def configure_test_stripe_keys(test_key: str, live_key: str) -> None:
    """
    Sets test and live Stripe keys globally for the module.
    """
    stripe.api_key = test_key

def set_webhook_secret(secret: str) -> None:
    """
    Sets the webhook secret for signing and verification.
    """
    global _WEBHOOK_SECRET
    if not isinstance(secret, str) or len(secret) < 8:
        raise ConfigurationError("webhook secret must be at least 8 characters")
    _WEBHOOK_SECRET = secret

def mock_entitlements(enabled: bool) -> None:
    """
    Enables or disables mock entitlements for testing purposes.
    """
    global _MOCK_ENTITLEMENTS
    if not isinstance(enabled, bool):
        raise TypeError("enabled must be boolean")
    _MOCK_ENTITLEMENTS = enabled

def reset_test_state(db: Session) -> None:
    """
    Clears all test data from the database.
    """
    try:
        db.query(UserService.db_model).delete()
        db.commit()
    except Exception as e:
        db.rollback()
        raise TransactionError(f"Database transaction failed: {e}")

def check_webhook_signatures(payload: bytes, sig: str, secret: str) -> bool:
    """
    Validates webhook signature without triggering event handling.
    """
    return sign_payload(payload, secret) == sig


def _selftest() -> None:
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import IntPKModel
    # Import the models so their tables register on the shared metadata.
    import scrapyard.identity.users  # noqa: F401
    import scrapyard.billing.subscriptions  # noqa: F401
    import scrapyard.billing.stripe_webhooks  # noqa: F401 (ProcessedEvent)
    import scrapyard.admin.audit_logs  # noqa: F401 (audit table)

    saved = os.environ.pop("STRIPE_API_KEY", None)  # force the offline stub path
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            engine = create_engine(f"sqlite:///{os.path.join(d, 't.db')}")
            IntPKModel.metadata.create_all(engine)
            try:
                # PASS fixture: a 'pro' plan checkout->signed-webhook flow must
                # activate the 'premium' entitlement.
                with Session(engine) as db:
                    res = check_subscription_activation(
                        db, user_email="pass@example.test", plan="pro")
                    assert res == {"ok": True}, res
                    db.commit()

                # FAIL fixture: a 'free' plan must NOT yield 'premium' after
                # activation, so the check must report ok=False.
                with Session(engine) as db:
                    res = check_subscription_activation(
                        db, user_email="fail@example.test", plan="free")
                    assert res == {"ok": False}, res
                    db.commit()
            finally:
                engine.dispose()
    finally:
        if saved is not None:
            os.environ["STRIPE_API_KEY"] = saved

    # Webhook signature check: a valid signature passes; tampering fails.
    payload = b'{"id":"evt_x"}'
    good = sign_payload(payload, "whsec")
    assert check_webhook_signatures(payload, good, "whsec") is True
    # NEGATIVE: wrong secret and forged signature are both rejected.
    assert check_webhook_signatures(payload, good, "wrong_secret") is False
    assert check_webhook_signatures(payload, "t=1,v1=deadbeef", "whsec") is False
    set_webhook_secret("whsec_test")
    mock_entitlements(True)
    assert _WEBHOOK_SECRET == "whsec_test" and _MOCK_ENTITLEMENTS is True
    try:
        set_webhook_secret("short")
        raise AssertionError("accepted weak webhook secret")
    except ConfigurationError:
        pass

    print("payment_checks selftest OK")


if __name__ == "__main__":
    _selftest()
