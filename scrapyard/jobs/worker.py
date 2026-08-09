"""
worker — Process that drains the durable job queue.

Run:  python -m scrapyard.jobs.worker --interval 1.0
Handlers are registered by the app (job_type -> callable(payload)). Run-once is
exposed for tests and single-tick drivers.

### PART-META-JSON
{
  "name": "worker",
  "layer": "jobs",
  "purpose": "Worker loop that claims and runs durable jobs, with a CLI entrypoint.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "run_worker(session_factory, handlers, interval=, worker_id=, max_ticks=); CLI flags --interval/--worker-id.",
  "outputs": "Drains the jobs table, dispatching each to its handler; returns a summary dict (for tests).",
  "files_created": [],
  "security_notes": "Each tick claims a single job under a row lock (see db_queue) so multiple worker processes are safe. A handler exception is caught and routed to retry/dead-letter, never crashing the loop. Register a real HANDLERS map before running in production; an empty map dead-letters everything (visible, not silent).",
  "ai_usage": "Provide a session_factory (callable -> db session, used in a `with` block) and a handlers dict. Use max_ticks in tests to run a bounded number of iterations.",
  "example": "from scrapyard.jobs.worker import run_worker; run_worker(SessionLocal, {'email.send': send_email}, max_ticks=10)",
  "import_path": "scrapyard.jobs.worker"
}
### END-PART-META
"""
from __future__ import annotations
import time

STATUS = "core"

# App registers real handlers here (job_type -> callable(payload) -> None).
HANDLERS: dict = {}


def run_worker(session_factory, handlers: dict | None = None, *, interval: float = 1.0,
               worker_id: str = "worker-1", max_ticks: int | None = None) -> dict:
    """Drain jobs until idle×patience (or max_ticks). session_factory() must yield a
    session usable as a context manager that commits on exit."""
    from scrapyard.jobs.db_queue import DBQueue
    q = DBQueue()
    handlers = handlers if handlers is not None else HANDLERS
    processed = 0
    idle_ticks = 0
    ticks = 0
    while True:
        ticks += 1
        with session_factory() as db:
            job = q.run_once(db, handlers, worker_id)
        if job:
            processed += 1
            idle_ticks = 0
        else:
            idle_ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            break
        if max_ticks is None:
            if idle_ticks:  # nothing to do; back off
                time.sleep(interval)
    return {"processed": processed, "ticks": ticks}


def _selftest() -> bool:
    """Offline: run the real worker loop against a temp SQLite DB for a few ticks."""
    import os
    import tempfile
    from contextlib import contextmanager
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import IntPKModel
    from scrapyard.jobs.db_queue import DBQueue

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        engine = create_engine(f"sqlite:///{os.path.join(td, 'jobs.db')}")
        IntPKModel.metadata.create_all(engine)

        @contextmanager
        def session_factory():
            with Session(engine) as s:
                yield s
                s.commit()

        q = DBQueue()
        seen: list = []
        handlers = {"email.send": lambda payload: seen.append(payload)}
        with session_factory() as db:
            q.enqueue(db, "email.send", {"to": "a@b"})
            q.enqueue(db, "email.send", {"to": "c@d"})
            q.enqueue(db, "no.handler", {})
        summary = run_worker(session_factory, handlers, max_ticks=6, worker_id="selftest")
        engine.dispose()
        assert summary["processed"] >= 2, summary
        assert {"to": "a@b"} in seen and {"to": "c@d"} in seen
    print("worker selftest OK")
    return True


def _main(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="scrapyard.jobs.worker")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--worker-id", default="worker-1")
    p.add_argument("--max-ticks", type=int, default=None)
    p.add_argument("--selftest", action="store_true",
                   help="run the offline selftest against a temp SQLite DB")
    args = p.parse_args(argv)
    if args.selftest:
        return 0 if _selftest() else 1
    try:
        from scrapyard.database.db_session import session_scope
        with session_scope():
            pass  # verify the engine is initialized before entering the loop
    except RuntimeError:
        # No configured database: don't crash, prove the loop offline instead.
        print("[worker] no database engine initialized "
              "(call init_engine(DATABASE_URL) in your app); running offline selftest")
        return 0 if _selftest() else 1
    print(f"[worker {args.worker_id}] draining jobs (interval={args.interval}s) "
          f"with {len(HANDLERS)} handler(s)")
    summary = run_worker(session_scope, HANDLERS, interval=args.interval,
                         worker_id=args.worker_id, max_ticks=args.max_ticks)
    print(f"[worker {args.worker_id}] {summary}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
