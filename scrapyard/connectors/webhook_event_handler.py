"""
webhook_event_handler — Handles incoming webhook events by validating, parsing, and routing them to appropriate handlers, ensuring secure and reliable event processing.

### PART-META-JSON
{
  "name": "webhook_event_handler",
  "layer": "connectors",
  "purpose": "Handles incoming webhook events by validating, parsing, and routing them to appropriate handlers, ensuring secure and reliable event processing.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "webhook_receiver_with_signature_verification"
  ],
  "inputs": "Public API: configure_webhook_handler(secret_key, db_path); register_handler(event_type, handler); get_metrics(); clear_metrics(); handle_webhook_event(event_data, signature); WebhookEvent(...); WebhookEventHandler(...).",
  "outputs": "Returns: configure_webhook_handler -> None; register_handler -> None; get_metrics -> List[Dict[str, Any]]; clear_metrics -> None; handle_webhook_event -> None.",
  "files_created": [],
  "security_notes": "Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import what you need from `scrapyard.connectors.webhook_event_handler`.",
  "example": "from scrapyard.connectors.webhook_event_handler import *",
  "import_path": "scrapyard.connectors.webhook_event_handler"
}
### END-PART-META
"""

import abc
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class WebhookEvent:
    event_id: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    raw_data: Optional[bytes] = None


class WebhookEventHandler(abc.ABC):
    @abc.abstractmethod
    def process_event(self, event: WebhookEvent) -> None:
        """Process the webhook event."""


# Module-level state
_handlers: Dict[str, WebhookEventHandler] = {}
_dedup_store: Optional[sqlite3.Connection] = None
_secret_key: bytes = b""
_metrics: List[Dict[str, Any]] = []


def configure_webhook_handler(secret_key: str, db_path: Optional[str] = None) -> None:
    """Configure the webhook handler with secret and optional dedup database."""
    global _secret_key, _dedup_store
    _secret_key = secret_key.encode() if isinstance(secret_key, str) else secret_key
    
    if db_path:
        _dedup_store = sqlite3.connect(db_path)
        _dedup_store.execute(
            "CREATE TABLE IF NOT EXISTS seen_events (event_id TEXT PRIMARY KEY, timestamp REAL)"
        )
        _dedup_store.commit()


def _verify_signature(payload: bytes, signature: str) -> bool:
    """Verify HMAC-SHA256 signature."""
    if not _secret_key:
        return False
    if signature.startswith("sha256="):
        sig = signature[7:]
    else:
        sig = signature
    expected = hmac.new(_secret_key, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _is_duplicate(event_id: str) -> bool:
    """Check if event is duplicate and record it if not."""
    if _dedup_store is None:
        return False
    cursor = _dedup_store.execute("SELECT 1 FROM seen_events WHERE event_id = ?", (event_id,))
    if cursor.fetchone() is not None:
        return True
    _dedup_store.execute("INSERT INTO seen_events VALUES (?, ?)", (event_id, time.time()))
    _dedup_store.commit()
    return False


def register_handler(event_type: str, handler: WebhookEventHandler) -> None:
    """Register a handler for a specific event type."""
    _handlers[event_type] = handler


def get_metrics() -> List[Dict[str, Any]]:
    """Return collected metrics."""
    return _metrics.copy()


def clear_metrics() -> None:
    """Clear collected metrics."""
    global _metrics
    _metrics = []


def handle_webhook_event(event_data: dict, signature: str) -> None:
    """
    Validates, parses, and routes webhook events.
    Logs outcomes and emits metrics. Prevents uncaught exceptions.
    """
    start_time = time.time()
    metric = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": event_data.get("event_id", "unknown"),
        "event_type": event_data.get("event_type", "unknown"),
        "success": False,
        "duplicate": False,
        "error": None,
        "duration_ms": 0,
    }
    
    try:
        # Canonical serialization for signature verification
        raw_payload = json.dumps(event_data, sort_keys=True, separators=(',', ':')).encode('utf-8')
        
        if not _verify_signature(raw_payload, signature):
            logger.warning("Signature verification failed for event %s", metric["event_id"])
            metric["error"] = "invalid_signature"
            return
        
        event_id = event_data.get("event_id")
        event_type = event_data.get("event_type")
        
        if not event_id or not event_type:
            logger.error("Missing event_id or event_type in payload")
            metric["error"] = "missing_fields"
            return
        
        if _is_duplicate(event_id):
            logger.info("Deduplicated event %s", event_id)
            metric["duplicate"] = True
            metric["success"] = True
            return
        
        event = WebhookEvent(
            event_id=event_id,
            event_type=event_type,
            payload=event_data.get("payload", {}),
            raw_data=raw_payload,
        )
        
        handler = _handlers.get(event_type)
        if handler:
            try:
                handler.process_event(event)
                logger.info("Successfully processed event %s", event_id)
                metric["success"] = True
            except Exception as e:
                logger.exception("Handler error for event %s", event_id)
                metric["error"] = str(type(e).__name__)
        else:
            logger.warning("No handler registered for event type %s", event_type)
            metric["error"] = "no_handler"
            
    except Exception as e:
        logger.exception("Unhandled exception processing webhook")
        metric["error"] = str(type(e).__name__)
    finally:
        metric["duration_ms"] = (time.time() - start_time) * 1000
        _metrics.append(metric)


def _selftest():
    """Self-test verifying all spec requirements."""
    
    class ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []
        def emit(self, record):
            self.records.append(record.getMessage())
    
    log_capture = ListHandler()
    logger.addHandler(log_capture)
    logger.setLevel(logging.DEBUG)
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "dedup.db")
        configure_webhook_handler("test-secret-key", db_path)
        clear_metrics()
        
        class TestHandler(WebhookEventHandler):
            def __init__(self):
                self.processed: List[WebhookEvent] = []
            def process_event(self, event: WebhookEvent) -> None:
                self.processed.append(event)
                if event.payload.get("trigger_error"):
                    raise ValueError("Simulated processing error")
        
        handler = TestHandler()
        register_handler("user.created", handler)
        
        def sign(payload: dict) -> str:
            raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
            return "sha256=" + hmac.new(b"test-secret-key", raw, hashlib.sha256).hexdigest()
        
        # 1. Signature verification rejects invalid signatures
        evt1 = {"event_id": "evt-001", "event_type": "user.created", "payload": {"name": "Alice"}}
        handle_webhook_event(evt1, "sha256=invalidsignature")
        m = get_metrics()[-1]
        assert m["error"] == "invalid_signature", "Should reject invalid signature"
        assert not m["success"]
        
        # 2. Event is parsed and routed correctly
        clear_metrics()
        sig1 = sign(evt1)
        handle_webhook_event(evt1, sig1)
        m = get_metrics()[-1]
        assert m["success"] is True, "Should process successfully"
        assert len(handler.processed) == 1
        assert handler.processed[0].event_id == "evt-001"
        
        # 3. Logging captures event details and outcomes
        assert any("Successfully processed event evt-001" in msg for msg in log_capture.records), "Should log success"
        
        # 4. Error handling prevents uncaught exceptions
        clear_metrics()
        evt2 = {"event_id": "evt-002", "event_type": "user.created", "payload": {"trigger_error": True}}
        try:
            handle_webhook_event(evt2, sign(evt2))
        except Exception:
            assert False, "Should not propagate exceptions"
        m = get_metrics()[-1]
        assert m["error"] == "ValueError"
        assert not m["success"]
        
        # 5. Metrics are emitted for each event processed
        clear_metrics()
        for i in range(3):
            e = {"event_id": f"evt-m{i}", "event_type": "user.created", "payload": {}}
            handle_webhook_event(e, sign(e))
        assert len(get_metrics()) == 3, "Should emit metric for each event"
        
        # 6. Event deduplication works as expected
        clear_metrics()
        dup_evt = {"event_id": "evt-dup", "event_type": "user.created", "payload": {"data": 1}}
        s = sign(dup_evt)
        handle_webhook_event(dup_evt, s)
        assert not get_metrics()[-1]["duplicate"], "First occurrence not duplicate"
        handle_webhook_event(dup_evt, s)
        assert get_metrics()[-1]["duplicate"], "Second occurrence should be duplicate"
        assert len([h for h in handler.processed if h.event_id == "evt-dup"]) == 1, "Handler called only once"
        
        # 7. Custom handler can be registered and invoked (verified in steps 2,4,6)
        
        if _dedup_store:
            _dedup_store.close()
    
    logger.removeHandler(log_capture)
    print("_selftest passed")


if __name__ == "__main__":
    _selftest()
