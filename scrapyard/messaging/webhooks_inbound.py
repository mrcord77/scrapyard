"""
webhooks_inbound — Verify + route inbound webhooks.

### PART-META-JSON
{
  "name": "webhooks_inbound",
  "layer": "messaging",
  "purpose": "Verify + route inbound webhooks.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Public API: verify_hmac(payload, signature, secret); WebhookVerificationError(...); WebhookRouteNotFoundError(...); WebhookDuplicateDeliveryError(...) (plus more).",
  "outputs": "Returns: verify_hmac -> bool.",
  "files_created": [],
  "security_notes": "Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `verify_hmac` from `scrapyard.messaging.webhooks_inbound` and call it as shown in `example`; run `py -m scrapyard.messaging.webhooks_inbound` to see its offline selftest.",
  "example": "from scrapyard.messaging.webhooks_inbound import verify_hmac",
  "import_path": "scrapyard.messaging.webhooks_inbound"
}
### END-PART-META
"""
from __future__ import annotations
import hashlib, hmac, json
import logging
from typing import Any, Callable, Dict, List, Optional, Union

STATUS = "core"

def verify_hmac(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

class WebhookVerificationError(Exception):
    pass

class WebhookRouteNotFoundError(Exception):
    pass

class WebhookDuplicateDeliveryError(Exception):
    pass

class UnsupportedHmacAlgorithmException(Exception):
    pass

class WebhookProcessingFailedError(Exception):
    pass

class InboundWebhooks:
    """Receive, verify, and route inbound webhooks idempotently by delivery id."""
    def __init__(self):
        self._seen = set()
        self._routes = {}
        self._logger = logging.getLogger(__name__)

    def on(self, event_type: str, handler):
        self._routes[event_type] = handler

    def receive(self, payload: bytes, signature: str, secret: str, *, delivery_id: str | None = None) -> dict:
        if not verify_hmac(payload, signature, secret):
            return {"ok": False, "error": "bad signature"}
        if delivery_id and delivery_id in self._seen:
            return {"ok": True, "status": "duplicate_ignored"}
        if delivery_id:
            self._seen.add(delivery_id)
        event = json.loads(payload.decode())
        h = self._routes.get(event.get("type"))
        if h:
            try:
                h(event)
            except Exception as e:
                self._logger.error(f"Error processing webhook: {e}")
                return {"ok": False, "error": "handler error"}
        return {"ok": True, "status": "processed", "type": event.get("type")}

    def register_webhook_route(self, event_type: str, handler: Callable[[Dict[str, Any]], None], priority: int = 0):
        if not callable(handler):
            raise ValueError("Handler must be a callable function")
        if event_type in self._routes:
            for existing_handler in self._routes[event_type]:
                if existing_handler.priority < handler.priority:
                    break
            else:
                self._routes[event_type].append(handler)
                return
        self._routes.setdefault(event_type, []).append(handler)

    def bulk_register_webhook_routes(self, routes: List[Dict[str, Union[str, Callable[[Dict[str, Any]], None], int]]]):
        for route in routes:
            if "event_type" not in route or "handler" not in route:
                raise ValueError("Each route must have 'event_type' and 'handler'")
            handler = route["handler"]
            priority = route.get("priority", 0)
            self.register_webhook_route(route["event_type"], handler, priority)

    def get_registered_routes(self) -> List[Dict[str, Union[str, Callable[[Dict[str, Any]], None], int]]]:
        routes = []
        for event_type, handlers in self._routes.items():
            for handler in handlers:
                routes.append({
                    "event_type": event_type,
                    "handler": handler,
                    "priority": handler.priority
                })
        return routes

    def get_delivery_status(self, delivery_id: str) -> Optional[Dict[str, Any]]:
        # This is a placeholder implementation; replace with actual logic if needed.
        return {"delivery_id": delivery_id, "status": "processed"}

    def clear_seen_deliveries(self):
        self._seen.clear()

    def _verify_hmac(self, payload: bytes, signature: str, secret: str, algorithm: str = "sha256") -> bool:
        if algorithm not in {"sha1", "sha256", "sha384", "sha512"}:
            raise UnsupportedHmacAlgorithmException(f"Unsupported HMAC algorithm: {algorithm}")
        expected = hmac.new(secret.encode(), payload, getattr(hashlib, algorithm)()).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_hmac_with_signature(self, payload: bytes, signature: str, secret: str, algorithm: str = "sha256") -> bool:
        return self._verify_hmac(payload, signature, secret, algorithm=algorithm)

    def process_webhook_with_retry(self, payload: bytes, signature: str, secret: str, delivery_id: Optional[str] = None, max_retries: int = 3, retry_delay: float = 1.0) -> Dict[str, Any]:
        for _ in range(max_retries + 1):
            if not self._verify_hmac(payload, signature, secret):
                return {"ok": False, "error": "bad signature"}
            if delivery_id and delivery_id in self._seen:
                return {"ok": True, "status": "duplicate_ignored"}
            if delivery_id:
                self._seen.add(delivery_id)
            event = json.loads(payload.decode())
            handlers = sorted(self._routes.get(event.get("type"), []), key=lambda h: h.priority, reverse=True)
            for handler in handlers:
                try:
                    handler(event)
                    return {"ok": True, "status": "processed", "type": event.get("type")}
                except Exception as e:
                    self._logger.error(f"Error processing webhook: {e}")
            if _ < max_retries:
                self._logger.warning(f"Webhook processing failed; retrying in {retry_delay} seconds...")
                import time
                time.sleep(retry_delay)
        return {"ok": False, "error": "processing failed after retries"}

    def log_webhook_event(self, event: Dict[str, Any], status: str, error: Optional[str] = None):
        self._logger.info(f"Webhook event logged - {event['type']}: {status}, {error}")

    def serialize_webhook_event(self, event: Dict[str, Any], format: str = "json") -> str:
        if format == "json":
            return json.dumps(event)
        elif format == "xml":
            try:
                from jinja2 import Template
                template = Template('<webhook><type>{{ type }}</type><data>{{ data|tojson }}</data></webhook>')
                return template.render(type=event["type"], data=json.dumps(event))
            except ImportError:
                raise RuntimeError("Jinja2 is required for XML serialization")
        else:
            raise ValueError(f"Unsupported serialization format: {format}")


def _selftest() -> None:
    """Offline, falsifiable self-test of inbound webhook verification + routing."""
    secret = "whsec_test"
    payload = json.dumps({"type": "invoice.paid", "id": "evt_1"}).encode()
    good_sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    # 1) a valid HMAC verifies; 2) NEGATIVE: a forged signature does not
    assert verify_hmac(payload, good_sig, secret) is True, "valid HMAC must verify"
    assert verify_hmac(payload, "deadbeef" * 8, secret) is False, "forged HMAC must fail"
    assert verify_hmac(payload, good_sig, "wrong-secret") is False, "wrong secret must fail"

    ib = InboundWebhooks()
    seen = []
    ib.on("invoice.paid", lambda ev: seen.append(ev["id"]))

    # 3) a verified webhook is routed to its handler
    res = ib.receive(payload, good_sig, secret, delivery_id="d1")
    assert res["ok"] is True and res.get("status") == "processed", "valid webhook must process"
    assert seen == ["evt_1"], "handler must have been invoked with the event"

    # 4) NEGATIVE: a bad signature is rejected and the handler is NOT invoked
    res_bad = ib.receive(payload, "00" * 32, secret, delivery_id="d2")
    assert res_bad["ok"] is False, "bad-signature webhook must be rejected"
    assert seen == ["evt_1"], "handler must not run for a bad signature"

    # 5) idempotency: a duplicate delivery_id is ignored (handler runs once)
    dup = ib.receive(payload, good_sig, secret, delivery_id="d1")
    assert dup.get("status") == "duplicate_ignored", "duplicate delivery must be ignored"
    assert seen == ["evt_1"], "duplicate must not re-invoke the handler"

    print("webhooks_inbound: OK (7 assertions incl. forged-sig + duplicate-delivery negatives)")


if __name__ == "__main__":
    _selftest()
