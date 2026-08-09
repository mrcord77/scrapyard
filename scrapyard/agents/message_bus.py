"""
message_bus — Facilitate inter-agent communication through a publish-subscribe message bus, enabling scalable and decoupled agent interactions.

### PART-META-JSON
{
  "name": "message_bus",
  "layer": "agents",
  "purpose": "Facilitate inter-agent communication through a publish-subscribe message bus, enabling scalable and decoupled agent interactions.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: MessageBus(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.agents.message_bus`.",
  "example": "from scrapyard.agents.message_bus import *",
  "import_path": "scrapyard.agents.message_bus"
}
### END-PART-META
"""

from typing import List, Dict, Any, Callable
import logging
import threading
import time

logger = logging.getLogger(__name__)

class MessageBus:
    def __init__(self):
        self.topics: Dict[str, List[Callable]] = {}
        self.lock = threading.Lock()

    def publish(self, topic: str, message: Any) -> None:
        with self.lock:
            if topic in self.topics:
                for callback in self.topics[topic]:
                    try:
                        callback(message)
                    except Exception as e:
                        logger.error(f"Error processing message on topic {topic}: {e}")

    def subscribe(self, topic: str, callback: Callable) -> None:
        with self.lock:
            if topic not in self.topics:
                self.topics[topic] = []
            self.topics[topic].append(callback)

    def unsubscribe(self, topic: str, callback: Callable) -> None:
        with self.lock:
            if topic in self.topics:
                self.topics[topic].remove(callback)
                if not self.topics[topic]:
                    del self.topics[topic]

def _selftest() -> bool:
    """Offline self-test: publish/subscribe delivers to subscribers of a topic and
    NOT to subscribers of other topics; unsubscribe stops delivery; a raising
    handler is isolated and does not break delivery to others."""
    bus = MessageBus()

    inbox_a: list = []
    inbox_b: list = []
    bus.subscribe("topic.a", inbox_a.append)
    bus.subscribe("topic.b", inbox_b.append)

    # Delivery goes only to the matching topic's subscribers.
    bus.publish("topic.a", "hello")
    assert inbox_a == ["hello"], f"subscriber A should have received the message, got {inbox_a}"
    assert inbox_b == [], f"subscriber B must NOT receive topic.a messages, got {inbox_b}"

    # Multiple subscribers on one topic all receive it.
    inbox_a2: list = []
    bus.subscribe("topic.a", inbox_a2.append)
    bus.publish("topic.a", "again")
    assert inbox_a == ["hello", "again"] and inbox_a2 == ["again"]

    # Publishing to a topic with no subscribers is a safe no-op.
    bus.publish("topic.nobody", "void")  # must not raise

    # Unsubscribe stops further delivery (use a named handler: a bound method like
    # list.append is a fresh object each access and would not match on removal).
    seen: list = []

    def handler(msg):
        seen.append(msg)

    bus.subscribe("topic.c", handler)
    bus.publish("topic.c", 1)
    bus.unsubscribe("topic.c", handler)
    bus.publish("topic.c", 2)
    assert seen == [1], f"unsubscribe must stop delivery, got {seen}"

    # Negative/adversarial: a handler that raises must be isolated so a co-subscriber
    # still receives the message (bus swallows and logs handler errors).
    good: list = []

    def boom(_msg):
        raise RuntimeError("handler blew up")

    bus.subscribe("topic.d", boom)
    bus.subscribe("topic.d", good.append)
    bus.publish("topic.d", "payload")  # must not propagate the RuntimeError
    assert good == ["payload"], f"a raising co-subscriber must not block delivery, got {good}"

    print("message_bus selftest: PASS")
    return True


if __name__ == "__main__":
    if not _selftest():
        raise SystemExit(1)
