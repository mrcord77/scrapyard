"""
webhooks_outbound — Signed, retried outbound webhook delivery.

### PART-META-JSON
{
  "name": "webhooks_outbound",
  "layer": "messaging",
  "purpose": "Signed, retried outbound webhook delivery.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: sign_payload(payload, secret); DeliveryError(...); DeliveryResult(...); DeliveryPolicy(...) (plus more).",
  "outputs": "Returns: sign_payload -> str.",
  "files_created": [],
  "security_notes": "Makes outbound network calls; set timeouts, validate URLs/hosts, and never send secrets to untrusted endpoints. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `sign_payload` from `scrapyard.messaging.webhooks_outbound` and call it as shown in `example`; run `py -m scrapyard.messaging.webhooks_outbound` to see its offline selftest.",
  "example": "from scrapyard.messaging.webhooks_outbound import sign_payload",
  "import_path": "scrapyard.messaging.webhooks_outbound"
}
### END-PART-META
"""
from __future__ import annotations
import hashlib
import hmac
import json
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel

STATUS = "core"


class DeliveryError(Exception):
    """Raised when a webhook cannot be delivered after all attempts."""


def sign_payload(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

class DeliveryResult(BaseModel):
    url: str
    ok: bool
    attempts: int
    timestamp: float

class DeliveryPolicy(BaseModel):
    max_attempts: int = 3
    retry_delay: int = 5
    timeout: int = 10

class OutboundWebhooks:
    """Deliver signed webhooks to subscriber URLs with retry + a delivery log.
    Network send is pluggable (set_sender) so it's testable offline."""
    
    def __init__(self, secret: str = "whsec"):
        self.secret = secret
        self.subscribers = {}
        self.deliveries = []
        self._sender = None
        self.delivery_policy = DeliveryPolicy()
        self.serializer = json.dumps
        self.audit_hook = None
        self.metrics_hook = None

    def set_sender(self, fn):
        self._sender = fn

    def add_webhook_subscriber(self, event_type: str, url: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append({"url": url, "metadata": metadata})

    def remove_webhook_subscriber(self, event_type: str, url: str) -> bool:
        if event_type in self.subscribers and url in [s["url"] for s in self.subscribers[event_type]]:
            self.subscribers[event_type] = [s for s in self.subscribers[event_type] if s["url"] != url]
            return True
        return False

    def list_subscribers(self, event_type: Optional[str] = None, filter_by: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if event_type:
            subscribers = self.subscribers.get(event_type, [])
        else:
            subscribers = [s for sublist in self.subscribers.values() for s in sublist]
        
        if filter_by:
            return [sub for sub in subscribers if all(sub[k] == v for k, v in filter_by.items())]
        return subscribers

    def deliver_with_retry(self, event_type: str, data: Dict[str, Any], max_attempts: int = 3, timeout: int = 10, retry_delay: int = 5,
                           filter_by: Optional[Dict[str, Any]] = None) -> List[DeliveryResult]:
        payload = self.serializer({"type": event_type, "data": data}).encode()
        sig = sign_payload(payload, self.secret)
        out = []

        subs = self.subscribers.get(event_type, [])
        if filter_by:
            subs = [sub for sub in subs
                    if all(sub.get(k) == v for k, v in filter_by.items())]
        for url in [s["url"] for s in subs]:
            ok, attempts = False, 0
            last_error: Optional[Exception] = None
            for attempts in range(1, max_attempts + 1):
                try:
                    (self._sender or self._default_send)(url, payload, sig)
                    ok = True
                    break
                except Exception as e:
                    last_error = e
                    if attempts < max_attempts:
                        time.sleep(retry_delay)
            if not ok and last_error is not None:
                raise DeliveryError(
                    f"failed to deliver to {url} after {max_attempts} attempts: {last_error}")
            rec = {"url": url, "ok": ok, "attempts": attempts, "timestamp": time.time()}
            self.deliveries.append(rec)
            out.append(rec)
        
        return out

    def get_delivery_log(self, event_type: Optional[str] = None, start: Optional[int] = None, limit: Optional[int] = None) -> List[DeliveryResult]:
        if event_type:
            delivery_log = [d for d in self.deliveries if d["url"].startswith(event_type)]
        else:
            delivery_log = self.deliveries
        
        if start is not None and limit is not None:
            return delivery_log[start:start+limit]
        
        return delivery_log

    def set_delivery_policy(self, policy: DeliveryPolicy):
        self.delivery_policy = policy

    def set_serializer(self, serializer: Callable[[Dict], bytes]):
        self.serializer = serializer

    def set_audit_hook(self, hook: Callable[[DeliveryResult], None]):
        self.audit_hook = hook

    def set_metrics_hook(self, hook: Callable[[DeliveryResult], None]):
        self.metrics_hook = hook

    def _default_send(self, url, payload, sig):
        import urllib.request
        req = urllib.request.Request(url, data=payload)
        req.add_header("X-Webhook-Signature", sig)
        req.add_header("content-type", "application/json")
        urllib.request.urlopen(req, timeout=self.delivery_policy.timeout)

    def sign_payload(self, payload: bytes, secret: str) -> str:
        return sign_payload(payload, secret)

    # -- original core API (kept stable) -------------------------------------
    def subscribe(self, event_type: str, url: str):
        self.add_webhook_subscriber(event_type, url)

    def emit(self, event_type: str, data: dict, *, max_attempts: int = 3) -> list:
        """Original best-effort delivery: failures are recorded, not raised."""
        payload = self.serializer({"type": event_type, "data": data}).encode()
        sig = sign_payload(payload, self.secret)
        out = []
        for url in [s["url"] for s in self.subscribers.get(event_type, [])]:
            ok, attempts = False, 0
            for attempts in range(1, max_attempts + 1):
                try:
                    (self._sender or self._default_send)(url, payload, sig)
                    ok = True
                    break
                except Exception:
                    continue
            rec = {"url": url, "ok": ok, "attempts": attempts}
            self.deliveries.append(rec)
            out.append(rec)
        return out


def _selftest() -> None:
    """Offline, falsifiable self-test of outbound signing + retry (pluggable sender,
    no real network)."""
    ow = OutboundWebhooks(secret="whsec_out")
    captured = []
    ow.set_sender(lambda url, payload, sig: captured.append((url, payload, sig)))
    ow.subscribe("order.created", "https://sub.example/hook")

    # 1) a subscribed URL receives exactly one signed delivery
    results = ow.deliver_with_retry("order.created", {"order": 1}, retry_delay=0)
    assert len(captured) == 1 and results[0]["ok"] is True, "delivery must succeed once"

    # 2) the delivered signature is a valid HMAC over the delivered payload
    url, payload, sig = captured[0]
    expected = sign_payload(payload, "whsec_out")
    assert hmac.compare_digest(sig, expected), "signature must match HMAC over payload"
    # NEGATIVE: the wrong secret would NOT produce this signature
    assert sig != sign_payload(payload, "attacker-secret"), "signature is secret-bound"

    # 3) a failing sender is retried up to max_attempts, then raises DeliveryError
    ow2 = OutboundWebhooks(secret="s")
    tries = {"n": 0}
    def _always_fail(url, payload, sig):
        tries["n"] += 1
        raise RuntimeError("boom")
    ow2.set_sender(_always_fail)
    ow2.subscribe("x", "https://down.example/hook")
    raised = False
    try:
        ow2.deliver_with_retry("x", {"a": 1}, max_attempts=3, retry_delay=0)
    except DeliveryError:
        raised = True
    assert raised, "exhausted retries must raise DeliveryError"
    assert tries["n"] == 3, "must attempt exactly max_attempts times before giving up"

    # 4) subscriber management: remove stops future deliveries
    assert ow.remove_webhook_subscriber("order.created", "https://sub.example/hook") is True
    captured.clear()
    ow.deliver_with_retry("order.created", {"order": 2}, retry_delay=0)
    assert captured == [], "removed subscriber must not receive deliveries"

    print("webhooks_outbound: OK (7 assertions incl. retry-exhaustion + secret-bound-sig negatives)")


if __name__ == "__main__":
    _selftest()
