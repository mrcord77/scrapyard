"""
db_queue — Durable, database-backed job queue (production path for the jobs layer).

Unlike the in-memory queue, jobs survive process restarts, are claimed with a lock
(so multiple workers don't double-run a job), retry with backoff, dead-letter after
exhausting attempts, and are idempotent by key. This is the queue the report's
notification/retention subsystems are meant to ride on.

### PART-META-JSON
{
  "name": "db_queue",
  "layer": "jobs",
  "purpose": "Durable database-backed job queue with locking, retry/backoff, dead-letter, and idempotency.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "enqueue(db, job_type, payload, max_attempts=, run_after=, idempotency_key=); claim_next(db, worker_id); run_once(db, handlers, worker_id); admin ops.",
  "outputs": "Persisted Job rows (queued/running/succeeded/failed/dead); run_once dispatches to a handler and records the outcome.",
  "files_created": [],
  "security_notes": "Jobs persist across restarts (durable, unlike the in-memory queue — which is a forbidden-in-production fallback). claim_next locks a row (FOR UPDATE SKIP LOCKED where supported) so concurrent workers never double-run a job; payloads must not contain secrets/PII in cleartext if the DB is shared. Idempotency keys prevent duplicate enqueue of the same logical job. Dead-lettered jobs are retained for inspection/replay, never silently dropped.",
  "ai_usage": "enqueue() to add work; run a worker (scrapyard.jobs.worker) or call run_once(db, handlers, worker_id) in a loop with handlers={job_type: callable(payload)->None}. Set JOBS_BACKEND=db in production; the in-memory queue is refused there.",
  "example": "from scrapyard.jobs.db_queue import DBQueue; q=DBQueue(); q.enqueue(db,'email.send',{'to':'a@b.co'}); q.run_once(db, {'email.send': lambda p: None}, 'w1')",
  "import_path": "scrapyard.jobs.db_queue"
}
### END-PART-META
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone

STATUS = "core"

from sqlalchemy import Integer, String, Text, DateTime, func, select
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import Base

QUEUED, RUNNING, SUCCEEDED, FAILED, DEAD = "queued", "running", "succeeded", "failed", "dead"


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(100), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default=QUEUED, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DBQueue:
    """Durable queue operating on a SQLAlchemy session passed per-call."""

    def __init__(self, *, backoff_base_seconds: float = 30.0):
        self.backoff_base = backoff_base_seconds

    def enqueue(self, db, job_type: str, payload: dict | None = None, *,
                max_attempts: int = 3, run_after: datetime | None = None,
                idempotency_key: str | None = None) -> Job:
        """Add a job. If idempotency_key matches a still-live (non-dead) job, return
        that one instead of inserting a duplicate."""
        if idempotency_key:
            existing = db.scalars(
                select(Job).where(Job.idempotency_key == idempotency_key,
                                  Job.status != DEAD).limit(1)).first()
            if existing:
                return existing
        job = Job(job_type=job_type, payload_json=json.dumps(payload or {}),
                  max_attempts=max_attempts, run_after=run_after or _now(),
                  idempotency_key=idempotency_key, status=QUEUED)
        db.add(job)
        db.flush()
        return job

    def claim_next(self, db, worker_id: str, *, now: datetime | None = None) -> Job | None:
        """Atomically claim the next runnable job (queued, or failed-and-due-for-retry),
        marking it running and locked. Returns None if nothing is runnable."""
        now = now or _now()
        stmt = (select(Job)
                .where(Job.status.in_([QUEUED, FAILED]),
                       Job.run_after <= now,
                       Job.attempts < Job.max_attempts)
                .order_by(Job.id).limit(1))
        try:
            stmt = stmt.with_for_update(skip_locked=True)  # Postgres/MySQL: no double-claim
        except Exception:
            pass
        try:
            job = db.scalars(stmt).first()
        except Exception:
            job = db.scalars(select(Job).where(Job.status.in_([QUEUED, FAILED]),
                                               Job.run_after <= now,
                                               Job.attempts < Job.max_attempts)
                             .order_by(Job.id).limit(1)).first()
        if not job:
            return None
        job.status = RUNNING
        job.locked_by = worker_id
        job.locked_at = now
        db.flush()
        return job

    def complete(self, db, job: Job) -> None:
        job.status = SUCCEEDED
        job.locked_by = None
        job.locked_at = None
        db.flush()

    def fail(self, db, job: Job, error: str) -> None:
        """Record a failure: retry with backoff until max_attempts, then dead-letter."""
        job.attempts += 1
        job.last_error = (error or "")[:2000]
        job.locked_by = None
        job.locked_at = None
        if job.attempts >= job.max_attempts:
            job.status = DEAD
        else:
            job.status = FAILED
            job.run_after = _now() + timedelta(seconds=self.backoff_base * job.attempts)
        db.flush()

    def run_once(self, db, handlers: dict, worker_id: str = "worker") -> Job | None:
        """Claim one job and dispatch it to handlers[job_type]. Records completion or
        failure (with retry/dead-letter). Returns the processed job, or None if idle."""
        job = self.claim_next(db, worker_id)
        if not job:
            return None
        handler = handlers.get(job.job_type)
        if handler is None:
            self.fail(db, job, f"no handler registered for job_type={job.job_type!r}")
            return job
        try:
            handler(json.loads(job.payload_json or "{}"))
            self.complete(db, job)
        except Exception as e:
            self.fail(db, job, f"{type(e).__name__}: {e}")
        return job

    # --- inspection / admin ---
    def stats(self, db) -> dict:
        rows = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
        return {s: n for s, n in rows}

    def dead_letters(self, db) -> list[Job]:
        return list(db.scalars(select(Job).where(Job.status == DEAD).order_by(Job.id)))

    def requeue(self, db, job_id: int) -> bool:
        """Reset a dead/failed job to queued for another run (manual replay)."""
        job = db.get(Job, job_id)
        if not job:
            return False
        job.status = QUEUED
        job.attempts = 0
        job.run_after = _now()
        job.last_error = ""
        db.flush()
        return True

    def cancel(self, db, job_id: int) -> bool:
        job = db.get(Job, job_id)
        if not job or job.status in (SUCCEEDED, DEAD):
            return False
        job.status = DEAD
        job.last_error = "cancelled"
        db.flush()
        return True


def _selftest() -> None:
    """Offline self-test: full lifecycle + retry/dead-letter over in-memory SQLite."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        engine = create_engine(f"sqlite:///{os.path.join(tmp, 't.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                q = DBQueue()

                # enqueue -> claim -> complete
                job = q.enqueue(db, "email.send", {"to": "a@b.co"})
                assert job.status == QUEUED
                claimed = q.claim_next(db, "w1")
                assert claimed is not None and claimed.id == job.id
                assert claimed.status == RUNNING and claimed.locked_by == "w1"
                q.complete(db, claimed)
                assert claimed.status == SUCCEEDED
                # negative: nothing runnable now -> claim returns None
                assert q.claim_next(db, "w1") is None, "empty queue must claim nothing"

                # idempotency: same key does not double-insert
                a = q.enqueue(db, "t", {}, idempotency_key="k1")
                b = q.enqueue(db, "t", {}, idempotency_key="k1")
                assert a.id == b.id, "idempotency key must dedupe enqueue"
                q.cancel(db, a.id)  # remove from the runnable set for the phases below

                # retry then dead-letter after max_attempts via run_once + failing handler.
                # (claim_next picks the lowest-id runnable job, so keep it the only one.)
                bad = q.enqueue(db, "explode", {}, max_attempts=2)
                handlers = {"explode": lambda p: (_ for _ in ()).throw(ValueError("boom"))}
                q.run_once(db, handlers, "w1")            # attempt 1 -> FAILED
                assert bad.status == FAILED and bad.attempts == 1
                bad.run_after = _now()                    # make it due again immediately
                db.flush()
                q.run_once(db, handlers, "w1")            # attempt 2 -> DEAD
                assert bad.status == DEAD, "job must dead-letter after max_attempts"
                assert any(j.id == bad.id for j in q.dead_letters(db))

                # replay: requeue a dead job resets it to queued
                assert q.requeue(db, bad.id) is True
                assert bad.status == QUEUED and bad.attempts == 0
                q.cancel(db, bad.id)  # clear it so the next phase's job is the only runnable

                # negative: unknown handler dead-letters the job (no silent success)
                nh = q.enqueue(db, "unknown.type", {}, max_attempts=1)
                q.run_once(db, {}, "w1")
                assert nh.status == DEAD, "job with no handler must not succeed"
                db.commit()
        finally:
            engine.dispose()
    print("db_queue self-test passed")


if __name__ == "__main__":
    _selftest()
