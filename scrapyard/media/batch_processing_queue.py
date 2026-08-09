"""
batch_processing_queue — Thread-pool batch queue with per-task retries, progress
callbacks, and ordered result collection for media (or any) processing jobs.

### PART-META-JSON
{
  "name": "batch_processing_queue",
  "layer": "media",
  "purpose": "Runs batches of tasks through a bounded thread worker pool with per-task retry (exponential backoff), progress/completion callbacks, cancellation, and a summary of successes and failures - built for media pipelines where individual items may fail transiently.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Callables plus args/kwargs submitted as tasks; worker count, max retry count, backoff base, and optional progress callback.",
  "outputs": "TaskResult records (task id, status, result or error, attempts) in submission order, plus a run summary dict.",
  "files_created": [],
  "security_notes": "Executes caller-supplied callables in worker threads - it never deserializes or evals data itself, so its risk is exactly the risk of the functions handed to it; do not submit callables built from untrusted input. Exceptions from tasks are captured with their message into TaskResult.error, so avoid raising exceptions containing secrets. Callbacks run on worker threads: they must be thread-safe. No network, filesystem, or subprocess use of its own.",
  "ai_usage": "q = BatchProcessingQueue(workers=4, max_retries=2); q.submit(fn, arg); results = q.run(); or one-shot process_batch(fn, items).",
  "example": "from scrapyard.media.batch_processing_queue import process_batch; results = process_batch(str.upper, ['a','b'])",
  "import_path": "scrapyard.media.batch_processing_queue"
}
### END-PART-META
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

ProgressCallback = Callable[["TaskResult", int, int], None]


@dataclass
class TaskResult:
    """Outcome of one queued task."""
    task_id: int
    status: str = "pending"  # pending | running | success | failed | cancelled
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    duration: float = 0.0


@dataclass
class _Task:
    task_id: int
    fn: Callable[..., Any]
    args: Tuple[Any, ...] = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)


class BatchProcessingQueue:
    """Bounded thread-pool queue with retries and progress reporting.

    Not a daemon service: build it, submit tasks, call run() (blocking) —
    results come back in submission order.
    """

    def __init__(self, workers: int = 4, max_retries: int = 0,
                 backoff_base: float = 0.05,
                 progress_callback: Optional[ProgressCallback] = None):
        if workers < 1:
            raise ValueError("workers must be >= 1")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self.workers = workers
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.progress_callback = progress_callback
        self._tasks: List[_Task] = []
        self._results: Dict[int, TaskResult] = {}
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._completed_count = 0

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> int:
        """Queue a task; returns its task id (submission index)."""
        if not callable(fn):
            raise ValueError("fn must be callable")
        with self._lock:
            task_id = len(self._tasks)
            self._tasks.append(_Task(task_id, fn, args, kwargs))
            self._results[task_id] = TaskResult(task_id)
        return task_id

    def cancel(self) -> None:
        """Stop dispatching further tasks; running tasks finish, pending become cancelled."""
        self._cancelled.set()

    def _report(self, result: TaskResult, total: int) -> None:
        if self.progress_callback is not None:
            try:
                self.progress_callback(result, self._completed_count, total)
            except Exception:
                pass  # a broken callback must not kill the batch

    def _run_one(self, task: _Task, total: int) -> None:
        res = self._results[task.task_id]
        res.status = "running"
        start = time.monotonic()
        for attempt in range(1, self.max_retries + 2):
            res.attempts = attempt
            try:
                res.result = task.fn(*task.args, **task.kwargs)
                res.status = "success"
                res.error = None
                break
            except Exception as exc:
                res.error = f"{type(exc).__name__}: {exc}"
                if attempt <= self.max_retries and not self._cancelled.is_set():
                    time.sleep(self.backoff_base * (2 ** (attempt - 1)))
                else:
                    res.status = "failed"
        res.duration = time.monotonic() - start
        with self._lock:
            self._completed_count += 1
        self._report(res, total)

    def _worker(self, q: "queue.Queue[Optional[_Task]]", total: int) -> None:
        while True:
            task = q.get()
            if task is None:
                q.task_done()
                return
            if self._cancelled.is_set():
                res = self._results[task.task_id]
                res.status = "cancelled"
                with self._lock:
                    self._completed_count += 1
                self._report(res, total)
            else:
                self._run_one(task, total)
            q.task_done()

    def run(self) -> List[TaskResult]:
        """Process all submitted tasks; blocks until done. Returns results in submission order."""
        with self._lock:
            tasks = list(self._tasks)
        total = len(tasks)
        if total == 0:
            return []
        q: "queue.Queue[Optional[_Task]]" = queue.Queue()
        for t in tasks:
            q.put(t)
        n_workers = min(self.workers, total)
        threads = []
        for _ in range(n_workers):
            q.put(None)  # one sentinel per worker
            th = threading.Thread(target=self._worker, args=(q, total), daemon=True)
            th.start()
            threads.append(th)
        for th in threads:
            th.join()
        return [self._results[t.task_id] for t in tasks]

    def summary(self) -> Dict[str, int]:
        """Counts by status for the current result set."""
        counts: Dict[str, int] = {"success": 0, "failed": 0, "cancelled": 0, "pending": 0}
        for r in self._results.values():
            counts[r.status] = counts.get(r.status, 0) + 1
        counts["total"] = len(self._results)
        return counts


def process_batch(fn: Callable[[Any], Any], items: Iterable[Any], *,
                  workers: int = 4, max_retries: int = 0,
                  progress_callback: Optional[ProgressCallback] = None) -> List[TaskResult]:
    """One-shot helper: apply fn to each item through the queue."""
    bq = BatchProcessingQueue(workers=workers, max_retries=max_retries,
                              progress_callback=progress_callback)
    for item in items:
        bq.submit(fn, item)
    return bq.run()


def _selftest() -> None:
    # 1. Ordered results, pure compute
    results = process_batch(lambda x: x * x, range(10), workers=3)
    assert [r.result for r in results] == [x * x for x in range(10)]
    assert all(r.status == "success" and r.attempts == 1 for r in results)

    # 2. Retry: fails twice then succeeds
    attempts_seen = {"n": 0}
    lock = threading.Lock()

    def flaky(x):
        with lock:
            attempts_seen["n"] += 1
            if attempts_seen["n"] < 3:
                raise RuntimeError("transient")
        return x + 1

    bq = BatchProcessingQueue(workers=1, max_retries=3, backoff_base=0.001)
    bq.submit(flaky, 41)
    (res,) = bq.run()
    assert res.status == "success" and res.result == 42 and res.attempts == 3, res

    # 3. Permanent failure captured, batch continues
    def boom(_):
        raise ValueError("bad item")

    bq = BatchProcessingQueue(workers=2, max_retries=1, backoff_base=0.001)
    bq.submit(boom, 1)
    bq.submit(lambda x: x, "ok")
    r_fail, r_ok = bq.run()
    assert r_fail.status == "failed" and "bad item" in r_fail.error
    assert r_fail.attempts == 2  # initial + 1 retry
    assert r_ok.status == "success" and r_ok.result == "ok"
    s = bq.summary()
    assert s["success"] == 1 and s["failed"] == 1 and s["total"] == 2

    # 4. Progress callback fires once per task with monotonic completion counts
    seen: List[int] = []
    cb_lock = threading.Lock()

    def on_progress(result: TaskResult, done: int, total: int) -> None:
        with cb_lock:
            seen.append(done)
        assert total == 5

    results = process_batch(lambda x: x, range(5), workers=2,
                            progress_callback=on_progress)
    assert len(seen) == 5 and max(seen) == 5

    # 5. Concurrency: 4 workers on 4 sleeping tasks finish ~1x not 4x
    t0 = time.monotonic()
    process_batch(lambda _: time.sleep(0.15), range(4), workers=4)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5, f"expected parallel execution, took {elapsed:.2f}s"

    # 6. Cancellation marks undispatched tasks cancelled
    bq = BatchProcessingQueue(workers=1)
    bq.submit(bq.cancel)  # first task cancels the queue
    for i in range(3):
        bq.submit(lambda x: x, i)
    results = bq.run()
    assert results[0].status == "success"
    assert all(r.status == "cancelled" for r in results[1:]), results

    print("batch_processing_queue selftest: all tests passed")


if __name__ == "__main__":
    _selftest()
