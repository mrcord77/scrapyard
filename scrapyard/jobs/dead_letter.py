"""
dead_letter — Dead-letter capture for exhausted jobs.

### PART-META-JSON
{
  "name": "dead_letter",
  "layer": "jobs",
  "purpose": "Dead-letter capture for exhausted jobs.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: DeadLetterQueue(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `DeadLetterQueue` from `scrapyard.jobs.dead_letter` and call it as shown in `example`; run `py -m scrapyard.jobs.dead_letter` to see its offline selftest.",
  "example": "from scrapyard.jobs.dead_letter import DeadLetterQueue",
  "import_path": "scrapyard.jobs.dead_letter"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

class DeadLetterQueue:
    """Holds jobs that exhausted their retries, with the failure reason, so they can
    be inspected and replayed rather than silently lost."""
    def __init__(self):
        self._items: list[dict] = []
    def add(self, job: dict, error: str) -> None:
        self._items.append({"job": job, "error": error})
    def list(self) -> list[dict]:
        return list(self._items)
    def replay(self, index: int, queue) -> bool:
        if 0 <= index < len(self._items):
            queue.enqueue(self._items.pop(index)["job"]); return True
        return False
    def size(self) -> int:
        return len(self._items)


def _selftest() -> None:
    """Offline self-test: capture + inspect + replay into a real queue."""
    from scrapyard.jobs.queues import InMemoryQueue

    dlq = DeadLetterQueue()
    assert dlq.size() == 0, "starts empty"

    j1 = {"id": 1, "type": "email"}
    j2 = {"id": 2, "type": "sms"}
    dlq.add(j1, "SMTP timeout")
    dlq.add(j2, "carrier rejected")
    assert dlq.size() == 2
    items = dlq.list()
    assert items[0] == {"job": j1, "error": "SMTP timeout"}, "captures job + reason"

    # replay pushes the job back onto a real queue and removes it from the DLQ
    target = InMemoryQueue()
    assert dlq.replay(0, target) is True
    assert dlq.size() == 1, "replayed item is removed from the dead-letter queue"
    assert target.dequeue() == j1, "replayed job lands on the target queue"

    # negative: an out-of-range index is a no-op that reports failure
    assert dlq.replay(99, target) is False, "invalid index must not replay"
    assert dlq.size() == 1, "failed replay must not mutate the queue"
    print("dead_letter self-test passed")


if __name__ == "__main__":
    _selftest()
