"""
background_tasks — Fire-and-forget tasks off the request path.

### PART-META-JSON
{
  "name": "background_tasks",
  "layer": "jobs",
  "purpose": "Thread-based background task submission with result/error capture (BackgroundTaskManager: submit/status/result/wait/cancel-pending), plus a queue-draining Worker with dead-letter handling and enforced queue/DLQ policies.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Callables + args for BackgroundTaskManager.submit; job dicts keyed by 'type' for Worker.",
  "outputs": "Task ids; TaskRecord objects with status/result/error/traceback; drain stats dicts.",
  "files_created": [],
  "security_notes": "Tasks run in daemon threads inside this process - a crashing task is captured (error + traceback string) and cannot kill the caller. No pickling/eval: payloads stay as in-process objects; serialize_task uses json only. Do not put secrets in job payloads that reach audit logs.",
  "ai_usage": "mgr = BackgroundTaskManager(max_workers=4); tid = mgr.submit(fn, *args); mgr.wait(tid); rec = mgr.get(tid) -> rec.status/result/error. Worker(queue) for job-dict pipelines with retries and DLQ.",
  "example": "from scrapyard.jobs.background_tasks import BackgroundTaskManager, Worker",
  "import_path": "scrapyard.jobs.background_tasks"
}
### END-PART-META
"""
from __future__ import annotations
import logging
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

STATUS = "core"
log = logging.getLogger("scrapyard.jobs")


# ---------------------------------------------------------------------------
# Thread-based background task submission (the fire-and-forget headline)
# ---------------------------------------------------------------------------

@dataclass
class TaskRecord:
    id: str
    name: str
    status: str = "pending"        # pending -> running -> done | failed | cancelled
    result: Any = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    _done: threading.Event = field(default_factory=threading.Event, repr=False)


class BackgroundTaskManager:
    """Real thread-based background execution with result/error capture.

    A bounded pool of daemon worker threads pulls submitted callables off an
    internal queue; each task's return value or exception (with traceback) is
    captured on its TaskRecord.
    """

    def __init__(self, max_workers: int = 4):
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self._tasks: Dict[str, TaskRecord] = {}
        self._pending: List[tuple] = []
        self._lock = threading.Lock()
        self._work_available = threading.Condition(self._lock)
        self._shutdown = False
        self._threads = [
            threading.Thread(target=self._worker_loop, daemon=True,
                             name=f"bgtask-worker-{i}")
            for i in range(max_workers)
        ]
        for t in self._threads:
            t.start()

    def _worker_loop(self) -> None:
        while True:
            with self._work_available:
                while not self._pending and not self._shutdown:
                    self._work_available.wait()
                if self._shutdown and not self._pending:
                    return
                record, fn, args, kwargs = self._pending.pop(0)
            if record.status == "cancelled":
                record._done.set()
                continue
            record.status = "running"
            try:
                record.result = fn(*args, **kwargs)
                record.status = "done"
            except Exception as e:
                record.status = "failed"
                record.error = f"{type(e).__name__}: {e}"
                record.traceback = traceback.format_exc()
                log.error("background task %s (%s) failed: %s", record.id, record.name, e)
            finally:
                record._done.set()

    def submit(self, fn: Callable, *args: Any, name: Optional[str] = None,
               **kwargs: Any) -> str:
        """Queue fn(*args, **kwargs) for background execution; returns a task id."""
        if not callable(fn):
            raise TypeError("submit requires a callable")
        record = TaskRecord(id=uuid.uuid4().hex, name=name or getattr(fn, "__name__", "task"))
        with self._work_available:
            if self._shutdown:
                raise RuntimeError("manager is shut down")
            self._tasks[record.id] = record
            self._pending.append((record, fn, args, kwargs))
            self._work_available.notify()
        return record.id

    def get(self, task_id: str) -> TaskRecord:
        rec = self._tasks.get(task_id)
        if rec is None:
            raise KeyError(f"unknown task id: {task_id}")
        return rec

    def status(self, task_id: str) -> str:
        return self.get(task_id).status

    def result(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """Block until the task finishes; return its result or re-raise its failure."""
        rec = self.get(task_id)
        if not rec._done.wait(timeout):
            raise TimeoutError(f"task {task_id} still {rec.status} after {timeout}s")
        if rec.status == "failed":
            raise RuntimeError(f"task {task_id} failed: {rec.error}")
        return rec.result

    def wait(self, task_id: str, timeout: Optional[float] = None) -> bool:
        return self.get(task_id)._done.wait(timeout)

    def wait_all(self, timeout: Optional[float] = None) -> bool:
        deadline = None if timeout is None else (threading.TIMEOUT_MAX if timeout < 0 else timeout)
        ok = True
        for rec in list(self._tasks.values()):
            ok = rec._done.wait(deadline) and ok
        return ok

    def cancel(self, task_id: str) -> bool:
        """Cancel a task that has not started yet. Running tasks cannot be stopped."""
        with self._lock:
            rec = self.get(task_id)
            if rec.status == "pending":
                rec.status = "cancelled"
                return True
            return False

    def shutdown(self, wait: bool = True) -> None:
        with self._work_available:
            self._shutdown = True
            self._work_available.notify_all()
        if wait:
            for t in self._threads:
                t.join(timeout=5)


_default_manager: Optional[BackgroundTaskManager] = None
_default_lock = threading.Lock()


def submit_background(fn: Callable, *args: Any, **kwargs: Any) -> str:
    """Module-level fire-and-forget on a shared default manager."""
    global _default_manager
    with _default_lock:
        if _default_manager is None:
            _default_manager = BackgroundTaskManager()
    return _default_manager.submit(fn, *args, **kwargs)


def get_default_manager() -> BackgroundTaskManager:
    global _default_manager
    with _default_lock:
        if _default_manager is None:
            _default_manager = BackgroundTaskManager()
    return _default_manager


# ---------------------------------------------------------------------------
# Queue-draining worker (job dicts + dead-letter), policies enforced
# ---------------------------------------------------------------------------

class Worker:
    """Pulls jobs off a queue and dispatches to registered handlers. Failed jobs
    retry, then land in the dead-letter queue. Synchronous drain() for tests;
    handlers are keyed by job['type']."""

    def __init__(self, queue, dlq=None, max_attempts: int = 3):
        from scrapyard.jobs.dead_letter import DeadLetterQueue
        self.queue = queue
        self.dlq = dlq or DeadLetterQueue()
        self.max_attempts = max_attempts
        self.handlers: Dict[str, Callable] = {}
        self._registry: Dict[str, dict] = {}   # task id -> job (status tracking)
        self._serializer = None
        self._queue_policy: Dict[str, Any] = {}
        self._dlq_policy: Dict[str, Any] = {}

    def register(self, job_type: str, handler: Callable) -> None:
        self.handlers[job_type] = handler

    def _run_one(self, job: dict) -> bool:
        h = self.handlers.get(job.get("type"))
        if not h:
            self._dead_letter(job, "no handler")
            return False
        attempts = int(self._queue_policy.get("max_attempts", self.max_attempts))
        for attempt in range(1, attempts + 1):
            try:
                h(job)
                job["status"] = "completed"
                return True
            except Exception as e:
                if attempt >= attempts:
                    self._dead_letter(job, str(e))
                    return False
        return False

    def _dead_letter(self, job: dict, error: str) -> None:
        job["status"] = "failed"
        self.dlq.add(job, error)
        max_size = self._dlq_policy.get("max_size")
        if max_size is not None and hasattr(self.dlq, "_items"):
            while len(self.dlq._items) > int(max_size):
                dropped = self.dlq._items.pop(0)
                log.warning("dead-letter retention dropped job %s",
                            dropped.get("job", {}).get("id"))

    def drain(self) -> dict:
        done = failed = 0
        while self.queue.size():
            job = self.queue.dequeue()
            if job is None:
                break
            if job.get("status") == "cancelled":
                continue
            if self._run_one(job):
                done += 1
            else:
                failed += 1
        return {"processed": done, "dead_lettered": failed}

    def enqueue_task(self, task_type: str, payload: dict = None, priority: int = 0) -> bool:
        job = {"type": task_type, "payload": payload, "priority": priority or 0,
               "status": "queued", "id": self._generate_task_id()}
        try:
            self.queue.enqueue(job)
        except Exception as e:
            log.error("enqueue failed: %s", e)
            return False
        self._registry[job["id"]] = job
        log.debug("Task %s enqueued.", job["id"])
        return True

    def enqueue_bulk(self, tasks: list) -> dict:
        stats = {"enqueued": 0, "failed": 0}
        for task in tasks:
            if self.enqueue_task(task["type"], task.get("payload"), task.get("priority", 0)):
                stats["enqueued"] += 1
            else:
                stats["failed"] += 1
        return stats

    def get_task_status(self, task_id: str) -> dict:
        job = self._registry.get(task_id)
        if job is None:
            raise KeyError(f"Task not found: {task_id}")
        return job

    def cancel_task(self, task_id: str) -> bool:
        """Mark a queued task cancelled; drain() skips cancelled jobs."""
        job = self._registry.get(task_id)
        if job and job.get("status") == "queued":
            job["status"] = "cancelled"
            log.info("Task %s cancelled.", task_id)
            return True
        return False

    def retry_failed_tasks(self) -> int:
        """Replay every dead-lettered job back onto the queue; returns count replayed."""
        replayed = 0
        while self.dlq.size():
            if self.dlq.replay(0, self.queue):
                replayed += 1
            else:
                break
        log.info("Replayed %d failed tasks.", replayed)
        return replayed

    def add_task_handler(self, task_type: str, handler: Callable) -> None:
        self.register(task_type, handler)

    def audit_task(self, task_id: str, metadata: dict) -> None:
        log.info("audit task=%s metadata=%s", task_id, metadata)

    def get_task_history(self, task_id: str) -> list:
        history = []
        job = self._registry.get(task_id)
        if job:
            history.append(job)
        for item in self.dlq.list():
            if item.get("job", {}).get("id") == task_id:
                history.append(item)
        return history

    def serialize_task(self, task: dict) -> str:
        from json import dumps
        return (self._serializer or dumps)(task)

    def deserialize_task(self, serialized: str) -> dict:
        from json import loads
        return loads(serialized)

    def set_queue_policy(self, policy_name: str, **kwargs) -> None:
        """Configure queue behavior. Supported: 'retry' (max_attempts=N)."""
        if policy_name == "retry":
            attempts = int(kwargs.get("max_attempts", self.max_attempts))
            if attempts < 1:
                raise ValueError("max_attempts must be >= 1")
            self._queue_policy["max_attempts"] = attempts
        else:
            raise ValueError(f"unknown queue policy: {policy_name}")
        log.debug("Queue policy %s set: %s", policy_name, kwargs)

    def get_queue_stats(self) -> dict:
        return {"queue_size": self.queue.size(), "dead_letter_size": self.dlq.size()}

    def set_dead_letter_policy(self, policy_name: str, **kwargs) -> None:
        """Configure DLQ behavior. Supported: 'retention' (max_size=N)."""
        if policy_name == "retention":
            max_size = int(kwargs.get("max_size", 0))
            if max_size < 1:
                raise ValueError("max_size must be >= 1")
            self._dlq_policy["max_size"] = max_size
        else:
            raise ValueError(f"unknown dead letter policy: {policy_name}")
        log.debug("Dead letter policy %s set: %s", policy_name, kwargs)

    def set_serializer(self, serializer: Callable) -> None:
        self._serializer = serializer

    @staticmethod
    def _generate_task_id() -> str:
        return uuid.uuid4().hex


def _selftest() -> bool:
    # --- BackgroundTaskManager: real threads, result + error capture ---
    mgr = BackgroundTaskManager(max_workers=2)
    t_ok = mgr.submit(lambda a, b: a + b, 2, 3, name="add")
    t_err = mgr.submit(lambda: 1 / 0, name="boom")
    assert mgr.wait(t_ok, timeout=5) and mgr.wait(t_err, timeout=5)
    assert mgr.result(t_ok) == 5
    rec = mgr.get(t_err)
    assert rec.status == "failed" and "ZeroDivisionError" in rec.error
    assert rec.traceback and "ZeroDivisionError" in rec.traceback
    try:
        mgr.result(t_err)
        raise AssertionError("failed task result must raise")
    except RuntimeError:
        pass

    # runs on a different thread than the caller
    import threading as _t
    tid_holder = {}
    t3 = mgr.submit(lambda: tid_holder.setdefault("tid", _t.get_ident()))
    mgr.wait(t3, timeout=5)
    assert tid_holder["tid"] != _t.get_ident()

    # cancel pending: saturate the pool with sleeps, then cancel a queued task
    import time as _time
    slow = [mgr.submit(_time.sleep, 0.3) for _ in range(2)]
    t_c = mgr.submit(lambda: "never")
    assert mgr.cancel(t_c) is True
    assert mgr.wait(t_c, timeout=5) and mgr.status(t_c) == "cancelled"
    assert mgr.wait_all(timeout=5)
    mgr.shutdown()

    # module-level fire-and-forget
    tid = submit_background(lambda: "bg")
    assert get_default_manager().result(tid, timeout=5) == "bg"

    # --- Worker: queue drain, DLQ, policies enforced ---
    from scrapyard.jobs.queues import InMemoryQueue
    q = InMemoryQueue()
    w = Worker(q, max_attempts=2)
    seen = []
    w.register("ok", lambda j: seen.append(j["payload"]))
    w.register("bad", lambda j: (_ for _ in ()).throw(RuntimeError("nope")))

    assert w.enqueue_task("ok", {"v": 1})
    assert w.enqueue_task("bad", {})
    assert w.enqueue_task("mystery", {})  # no handler -> DLQ
    stats = w.drain()
    assert stats == {"processed": 1, "dead_lettered": 2}, stats
    assert seen == [{"v": 1}]
    assert w.get_queue_stats() == {"queue_size": 0, "dead_letter_size": 2}

    # cancel prevents execution
    assert w.enqueue_task("ok", {"v": 2})
    tid2 = [j for j in w._registry.values() if j["status"] == "queued"][0]["id"]
    assert w.cancel_task(tid2)
    assert w.drain()["processed"] == 0
    assert w.get_task_status(tid2)["status"] == "cancelled"

    # retry_failed_tasks replays DLQ onto the queue
    assert w.retry_failed_tasks() == 2
    assert q.size() == 2 and w.dlq.size() == 0
    w.register("mystery", lambda j: None)
    w.register("bad", lambda j: None)  # now succeeds
    assert w.drain() == {"processed": 2, "dead_lettered": 0}

    # policies are real: retention trims DLQ, retry policy changes attempts
    w.set_dead_letter_policy("retention", max_size=1)
    w.register("bad", lambda j: (_ for _ in ()).throw(RuntimeError("x")))
    w.enqueue_task("bad", {})
    w.enqueue_task("bad", {})
    w.drain()
    assert w.dlq.size() == 1  # trimmed to policy
    attempts = {"n": 0}

    def counting(j):
        attempts["n"] += 1
        raise RuntimeError("always")

    w.register("count", counting)
    w.set_queue_policy("retry", max_attempts=4)
    w.enqueue_task("count", {})
    w.drain()
    assert attempts["n"] == 4, attempts
    try:
        w.set_queue_policy("nonsense")
        raise AssertionError("unknown policy accepted")
    except ValueError:
        pass

    # serialization
    job = {"type": "ok", "payload": {"v": 3}}
    assert w.deserialize_task(w.serialize_task(job)) == job

    print("background_tasks selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
