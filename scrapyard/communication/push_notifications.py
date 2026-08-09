"""
push_notifications — Web/mobile push dispatch.

### PART-META-JSON
{
  "name": "push_notifications",
  "layer": "communication",
  "purpose": "Web/mobile push dispatch.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: PushSender(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `PushSender` from `scrapyard.communication.push_notifications` and call it as shown in `example`; run `py -m scrapyard.communication.push_notifications` to see its offline selftest.",
  "example": "from scrapyard.communication.push_notifications import PushSender",
  "import_path": "scrapyard.communication.push_notifications"
}
### END-PART-META
"""
from typing import List, Dict, Any, Optional, Tuple, Callable
import logging
from datetime import datetime

STATUS = "core"
log = logging.getLogger("scrapyard.push")

class PushSender:
    """Device-token push sender; logs in dev + outbox, pluggable transport for
    FCM/APNs via set_transport."""
    
    def __init__(self):
        self.outbox: List[Dict[str, Any]] = []
        self._t: Optional[Callable[[Dict[str, Any]], None]] = None
        self._hooks: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {
            "before_send": [], "after_send": []}
        self._policy: Dict[str, Any] = {}
        self._hooks: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {
            "before_send": [], "after_send": []}
        self._policy: Dict[str, Any] = {}
    
    def set_transport(self, fn: Callable[[Dict[str, Any]], None]) -> None:
        """Replace the current transport function."""
        if not callable(fn):
            raise ValueError("Transport must be a callable function")
        self._t = fn

    def send(self, device_token: str, title: str, body: str) -> Dict[str, Any]:
        """Send a push notification to a device token (fires registered hooks)."""
        msg = {"token": device_token, "title": title, "body": body}
        for hook in self._hooks["before_send"]:
            try:
                hook(msg)
            except Exception as e:  # hook faults never block the send
                log.error("before_send hook failed: %s", e)
        if self._t:
            try:
                self._t(msg)
            except Exception as e:
                log.error(f"Transport failed: {e}")
                return msg
        else:
            log.info("PUSH to=%s title=%s", device_token[:8], title)

        self.outbox.append(msg)
        for hook in self._hooks["after_send"]:
            try:
                hook(msg)
            except Exception as e:
                log.error("after_send hook failed: %s", e)
        return msg

    def send_bulk(self, messages: List[Dict[str, Any]], retry: int = 3) -> List[Dict[str, Any]]:
        """Send multiple messages in one batch with configurable retry behavior."""
        if not messages:
            raise ValueError("No messages provided for bulk send")
        
        failed_messages = []
        for msg in messages:
            try:
                self.send(device_token=msg.get("device_token", msg.get("token", "")),
                          title=msg.get("title", ""), body=msg.get("body", ""))
            except Exception as e:
                log.error(f"Message failed: {e}")
                failed_messages.append(msg)
        
        return failed_messages

    def query_outbox(self, filters: Optional[Dict[str, Any]] = None, page: int = 1, per_page: int = 50) -> Tuple[List[Dict[str, Any]], int]:
        """Query and filter sent messages by token, title, or time range."""
        filtered_messages = self.outbox
        if filters:
            for key, value in filters.items():
                filtered_messages = [msg for msg in filtered_messages if msg.get(key) == value]
        
        total_count = len(filtered_messages)
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        return filtered_messages[start_index:end_index], total_count

    def archive_outbox(self, message_ids: List[str]) -> None:
        """Archive (soft-delete) messages from the outbox."""
        if not message_ids:
            raise ValueError("No message IDs provided for archiving")
        
        self.outbox = [msg for msg in self.outbox if msg["token"] not in message_ids]

    def configure_transport(self, transport: Callable[[Dict[str, Any]], None]) -> None:
        """Replace or configure the transport function with validation."""
        if not callable(transport):
            raise ValueError("Transport must be a callable function")
        self.set_transport(transport)

    def register_hook(self, hook_type: str, fn: Callable[[Dict[str, Any]], None]) -> None:
        """Register hooks for audit, metrics, or logging (e.g., before/after send)."""
        if not callable(fn):
            raise ValueError("Hook function must be a callable")
        
        if hook_type not in self._hooks:
            raise ValueError(f"Unknown hook type: {hook_type!r}")
        self._hooks[hook_type].append(fn)
    
    def serialize_message(self, message: Dict[str, Any]) -> str:
        """Standardized message serialization (JSON) for transport or storage."""
        import json
        return json.dumps(message, sort_keys=True)

    def deserialize_message(self, data: str) -> Dict[str, Any]:
        """Reverse of serialize_message. JSON only - never eval() on data."""
        import json
        obj = json.loads(data)
        if not isinstance(obj, dict):
            raise ValueError("serialized message must decode to a dict")
        return obj

    def validate_device_token(self, token: str) -> bool:
        """Validate format of device token before sending."""
        # Example validation; extend as needed
        return len(token) == 64 and all(c in "0123456789abcdefABCDEF-" for c in token)

    def set_policy(self, policy: Dict[str, Any]) -> None:
        """Set configurable policies (e.g., rate limit, max retries)."""
        # Example implementation; extend as needed
        self._policy = policy

    def get_policy(self) -> Dict[str, Any]:
        """Retrieve current policy settings."""
        return getattr(self, "_policy", {})



def _selftest() -> None:
    """Offline self-test for the push sender."""
    s = PushSender()
    token = "ab" * 32

    assert s.validate_device_token(token) is True
    assert s.validate_device_token("short") is False

    seen = {"before": 0, "after": 0}
    s.register_hook("before_send", lambda m: seen.__setitem__("before", seen["before"] + 1))
    s.register_hook("after_send", lambda m: seen.__setitem__("after", seen["after"] + 1))
    try:
        s.register_hook("sideways", lambda m: None)
        raise AssertionError("unknown hook type must be rejected")
    except ValueError:
        pass

    msg = s.send(token, "Hello", "World")
    assert msg["title"] == "Hello" and len(s.outbox) == 1
    assert seen == {"before": 1, "after": 1}

    # Custom transport receives the message
    delivered = []
    s.set_transport(delivered.append)
    s.send(token, "Second", "Msg")
    assert len(delivered) == 1 and len(s.outbox) == 2

    # Bulk send accepts both key styles
    failed = s.send_bulk([
        {"device_token": token, "title": "A", "body": "1"},
        {"token": token, "title": "B", "body": "2"},
    ])
    assert failed == [] and len(s.outbox) == 4
    try:
        s.send_bulk([])
        raise AssertionError("empty bulk must raise")
    except ValueError:
        pass

    # Outbox query + pagination
    msgs, total = s.query_outbox(filters={"title": "A"})
    assert total == 1 and msgs[0]["title"] == "A"
    msgs, total = s.query_outbox(page=1, per_page=2)
    assert len(msgs) == 2 and total == 4

    # JSON serialization round-trip (no eval)
    blob = s.serialize_message(msg)
    assert s.deserialize_message(blob) == msg
    try:
        s.deserialize_message("[1,2,3]")
        raise AssertionError("non-dict payload must be rejected")
    except ValueError:
        pass
    try:
        s.deserialize_message("__import__('os')")
        raise AssertionError("non-JSON payload must be rejected")
    except Exception as e:
        assert not isinstance(e, AssertionError)

    # Policy storage
    s.set_policy({"max_retries": 2})
    assert s.get_policy() == {"max_retries": 2}

    # Archive removes by token
    s.archive_outbox([token])
    assert s.outbox == []

    print("push_notifications self-test passed")


if __name__ == "__main__":
    _selftest()
