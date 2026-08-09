"""
event_bus — In-process pub/sub for domain events.

### PART-META-JSON
{
  "name": "event_bus",
  "layer": "messaging",
  "purpose": "In-process pub/sub for domain events with versioned subscribers, JSON event (de)serialization via a type registry, delivery policies (at_least_once retry / best_effort), and publish lifecycle callbacks.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Event names, JSON-serializable payloads, handler callables.",
  "outputs": "PublishResult per publish; EventMetrics counters; optional JSONL archive file.",
  "files_created": [],
  "security_notes": "deserialize_event uses json.loads plus an explicit type registry - never eval. Handler exceptions are isolated (logged + collected), so one bad subscriber cannot poison the bus. Archive lines contain payloads: do not archive events carrying secrets/PII.",
  "ai_usage": "bus.subscribe('user.created', handler); bus.publish('user.created', {...}). bus.set_delivery_policy(AtLeastOncePolicy(max_retries=3)) to retry failing handlers. register_event_type('user.created', UserModel-like factory) for typed deserialization.",
  "example": "from scrapyard.messaging.event_bus import bus",
  "import_path": "scrapyard.messaging.event_bus"
}
### END-PART-META
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

STATUS = "core"
log = logging.getLogger("scrapyard.events")


@dataclass
class PublishResult:
    event: str
    delivered: int
    errors: List[str]


@dataclass
class EventMetrics:
    total_events: int
    successful: int
    failed: int


@dataclass
class BestEffortPolicy:
    """Deliver once; handler errors are recorded and skipped (the default)."""
    pass


@dataclass
class AtLeastOncePolicy:
    """Retry a failing handler up to max_retries extra attempts before recording the error."""
    max_retries: int = 3


# Back-compat aliases (older code imported Sync/Async policies)
SyncPolicy = BestEffortPolicy
AsyncPolicy = AtLeastOncePolicy
DeliveryPolicy = Union[BestEffortPolicy, AtLeastOncePolicy]


class EventBus:
    """In-process pub/sub: subscribe handlers to event names, publish to all. Errors
    in one handler don't stop the others (logged + collected)."""

    def __init__(self):
        self._subs: Dict[str, Dict[str, List[Callable]]] = {}
        self._metrics = EventMetrics(total_events=0, successful=0, failed=0)
        self._archive_path: Optional[str] = None
        self._on_publish_callbacks: List[Callable[[PublishResult], None]] = []
        self._on_pre_publish_callbacks: List[Callable[[str, Any], None]] = []
        self._on_post_publish_callbacks: List[Callable[[PublishResult], None]] = []
        self._delivery_policy: DeliveryPolicy = BestEffortPolicy()
        self._type_registry: Dict[str, Callable[[dict], Any]] = {}

    # -- subscriptions -------------------------------------------------------
    def subscribe(self, event: str, handler: Callable[[Any], None], version: str = "v1") -> None:
        self._subs.setdefault(event, {}).setdefault(version, []).append(handler)

    def unsubscribe(self, event: str, handler: Callable, version: str = "v1") -> bool:
        try:
            self._subs.get(event, {}).get(version, []).remove(handler)
            return True
        except ValueError:
            return False

    def get_subscribers(self, event: str, version: Optional[str] = None) -> List[Callable]:
        return (self._subs.get(event, {}).get(version, []) if version else
                [h for v in self._subs.get(event, {}).values() for h in v])

    # -- delivery policy (REAL: consulted by publish) ------------------------
    def set_delivery_policy(self, policy: DeliveryPolicy) -> None:
        if not isinstance(policy, (BestEffortPolicy, AtLeastOncePolicy)):
            raise TypeError(
                f"policy must be BestEffortPolicy or AtLeastOncePolicy, got {type(policy).__name__}")
        self._delivery_policy = policy

    def get_delivery_policy(self) -> DeliveryPolicy:
        return self._delivery_policy

    # -- lifecycle callbacks -------------------------------------------------
    def on_publish(self, callback: Callable[[PublishResult], None]) -> None:
        self._on_publish_callbacks.append(callback)

    def on_pre_publish(self, callback: Callable[[str, Any], None]) -> None:
        self._on_pre_publish_callbacks.append(callback)

    def on_post_publish(self, callback: Callable[[PublishResult], None]) -> None:
        self._on_post_publish_callbacks.append(callback)

    # -- archive -------------------------------------------------------------
    def set_archive_path(self, path: str) -> None:
        self._archive_path = path

    def _archive(self, event: str, payload: Any) -> None:
        if not self._archive_path:
            return
        try:
            with open(self._archive_path, "a", encoding="utf-8") as f:
                f.write(self.serialize_event(event, payload) + "\n")
        except Exception as e:  # archival must not break publishing
            log.error("archive write failed: %s", e)

    # -- (de)serialization: json + type registry, never eval -----------------
    def register_event_type(self, event: str, factory: Callable[[dict], Any]) -> None:
        """Register a factory used to rebuild typed payloads on deserialize."""
        self._type_registry[event] = factory

    def serialize_event(self, event: str, payload: Any) -> str:
        return json.dumps({"event": event, "payload": payload}, sort_keys=True, default=str)

    def deserialize_event(self, event: str, data: str) -> Any:
        """json.loads + optional registered factory. Raises ValueError on non-JSON."""
        try:
            obj = json.loads(data)
        except (TypeError, ValueError) as e:
            raise ValueError(f"event data is not valid JSON: {e}")
        payload = obj.get("payload", obj) if isinstance(obj, dict) and "event" in obj else obj
        factory = self._type_registry.get(event)
        if factory is not None and isinstance(payload, dict):
            return factory(payload)
        return payload

    # -- publishing ----------------------------------------------------------
    def _deliver(self, handler: Callable, payload: Any, event: str) -> Optional[str]:
        """Deliver to one handler under the current policy. Returns error string or None."""
        attempts = 1
        if isinstance(self._delivery_policy, AtLeastOncePolicy):
            attempts += max(0, self._delivery_policy.max_retries)
        last_err: Optional[str] = None
        for i in range(attempts):
            try:
                handler(payload)
                return None
            except Exception as e:
                last_err = str(e)
                log.error("handler failed for %s (attempt %d/%d): %s", event, i + 1, attempts, e)
        return last_err

    def publish(self, event: str, payload: Any) -> PublishResult:
        for cb in self._on_pre_publish_callbacks:
            try:
                cb(event, payload)
            except Exception as e:
                log.error("pre-publish callback failed: %s", e)

        delivered, errors = 0, []
        for version, handlers in self._subs.get(event, {}).items():
            for handler in handlers:
                err = self._deliver(handler, payload, event)
                if err is None:
                    delivered += 1
                else:
                    errors.append(err)

        result = PublishResult(event=event, delivered=delivered, errors=errors)
        self._metrics.total_events += 1
        self._metrics.successful += int(not errors)
        self._metrics.failed += int(bool(errors))
        self._archive(event, payload)

        for cb in self._on_publish_callbacks + self._on_post_publish_callbacks:
            try:
                cb(result)
            except Exception as e:
                log.error("publish callback failed: %s", e)
        return result

    def publish_with_filters(self, event: str, payload: Any,
                             filters: Dict[str, Any]) -> PublishResult:
        """Publish only if the payload matches every filter key/value; else skip."""
        if isinstance(payload, dict):
            for k, v in filters.items():
                if payload.get(k) != v:
                    return PublishResult(event, 0, [f"filtered out: {k}!={v!r}"])
        return self.publish(event, payload)

    def bulk_publish(self, events: List[str], payloads: List[Any]) -> List[PublishResult]:
        return [self.publish(e, p) for e, p in zip(events, payloads)]

    def get_metrics(self) -> EventMetrics:
        return self._metrics


bus = EventBus()


def _selftest() -> bool:
    b = EventBus()
    seen: List[Any] = []
    b.subscribe("user.created", seen.append)
    r = b.publish("user.created", {"id": 1})
    assert r.delivered == 1 and not r.errors and seen == [{"id": 1}]

    # handler isolation: one failing handler doesn't stop the others
    b.subscribe("user.created", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    r = b.publish("user.created", {"id": 2})
    assert r.delivered == 1 and len(r.errors) == 1

    # delivery policy is REAL: at_least_once retries until success
    calls = {"n": 0}

    def flaky(p):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")

    b2 = EventBus()
    b2.subscribe("job.run", flaky)
    b2.set_delivery_policy(AtLeastOncePolicy(max_retries=3))
    r = b2.publish("job.run", {})
    assert r.delivered == 1 and not r.errors and calls["n"] == 3, calls

    # best_effort: single attempt
    calls["n"] = 0
    b2.set_delivery_policy(BestEffortPolicy())
    r = b2.publish("job.run", {})
    assert calls["n"] == 1 and r.errors  # first call after reset raises
    try:
        b2.set_delivery_policy("nonsense")  # type: ignore[arg-type]
        raise AssertionError("bad policy accepted")
    except TypeError:
        pass

    # serialization: json roundtrip, no eval, registry rebuilds types
    s = b.serialize_event("user.created", {"id": 3, "name": "a"})
    assert b.deserialize_event("user.created", s) == {"id": 3, "name": "a"}
    try:
        b.deserialize_event("user.created", "__import__('os').system('echo x')")
        raise AssertionError("non-JSON accepted")
    except ValueError:
        pass

    class User:
        def __init__(self, d):
            self.id = d["id"]

    b.register_event_type("user.created", User)
    u = b.deserialize_event("user.created", s)
    assert isinstance(u, User) and u.id == 3

    # filters
    r = b2.publish_with_filters("job.run", {"tenant": "a"}, {"tenant": "b"})
    assert r.delivered == 0 and r.errors

    # archive + metrics
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        b3 = EventBus()
        b3.set_archive_path(path)
        b3.subscribe("x", lambda p: None)
        b3.publish("x", {"k": 1})
        with open(path, encoding="utf-8") as f:
            line = json.loads(f.readline())
        assert line == {"event": "x", "payload": {"k": 1}}
        m = b3.get_metrics()
        assert m.total_events == 1 and m.successful == 1 and m.failed == 0
    finally:
        os.unlink(path)

    print("event_bus selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
