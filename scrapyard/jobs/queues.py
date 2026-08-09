"""
queues — Enqueue/consume via Redis/RQ/Celery adapter.

### PART-META-JSON
{
  "name": "queues",
  "layer": "jobs",
  "purpose": "Enqueue/consume via Redis/RQ/Celery adapter.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "redis"
  ],
  "inputs": "Public API: enqueue(job, queue); InMemoryQueue(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `enqueue` from `scrapyard.jobs.queues` and call it as shown in `example`; run `py -m scrapyard.jobs.queues` to see its offline selftest.",
  "example": "from scrapyard.jobs.queues import enqueue",
  "import_path": "scrapyard.jobs.queues"
}
### END-PART-META
"""
from __future__ import annotations
import threading
from collections import deque
STATUS = "core"

class InMemoryQueue:
    """Thread-safe FIFO job queue. The broker-agnostic default; swap for Redis/SQS
    in production by matching this interface (enqueue/dequeue/size)."""
    def __init__(self):
        self._q = deque(); self._lock = threading.Lock()
    def enqueue(self, job: dict) -> None:
        with self._lock:
            self._q.append(job)
    def dequeue(self):
        with self._lock:
            return self._q.popleft() if self._q else None
    def size(self) -> int:
        with self._lock:
            return len(self._q)

default_queue = InMemoryQueue()
def enqueue(job: dict, queue: InMemoryQueue | None = None):
    (queue or default_queue).enqueue(job)


def _selftest() -> None:
    """Offline self-test: FIFO ordering + empty-queue behaviour."""
    q = InMemoryQueue()
    assert q.size() == 0
    # negative: dequeue on an empty queue returns None (never raises/blocks)
    assert q.dequeue() is None, "empty queue must yield None"

    q.enqueue({"n": 1})
    q.enqueue({"n": 2})
    assert q.size() == 2
    # FIFO ordering is preserved
    assert q.dequeue() == {"n": 1}, "first in must be first out"
    assert q.dequeue() == {"n": 2}
    assert q.size() == 0

    # module-level helper routes to a provided queue
    enqueue({"n": 3}, q)
    assert q.size() == 1 and q.dequeue() == {"n": 3}
    print("queues self-test passed")


if __name__ == "__main__":
    _selftest()
