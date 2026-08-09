"""
jobs_admin_routes — Admin API for the durable job queue (inspect, retry, cancel).

### PART-META-JSON
{
  "name": "jobs_admin_routes",
  "layer": "jobs",
  "purpose": "Admin endpoints to inspect, retry, and cancel durable jobs.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi",
    "sqlalchemy"
  ],
  "inputs": "build_jobs_admin_router(get_db): GET /admin/jobs, GET /admin/jobs/{id}, POST /admin/jobs/{id}/retry, POST /admin/jobs/{id}/cancel.",
  "outputs": "Job listings/details and retry/cancel results.",
  "files_created": [],
  "security_notes": "These expose operational data and mutate job state — gate behind admin authorization (roles/permissions) before mounting; the router itself does not enforce admin (compose it under an admin-guarded prefix). Job payloads may be sensitive; restrict who can read them.",
  "ai_usage": "router = build_jobs_admin_router(get_db); mount under an admin-authorized prefix.",
  "example": "from scrapyard.jobs.jobs_admin_routes import build_jobs_admin_router; app.include_router(build_jobs_admin_router(get_db))",
  "import_path": "scrapyard.jobs.jobs_admin_routes"
}
### END-PART-META
"""
from __future__ import annotations

import logging
from typing import List, Optional, TypeVar, Any
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session
from scrapyard.jobs.db_queue import Job, DBQueue
from sqlalchemy import select

STATUS = "core"

logger = logging.getLogger(__name__)

TJob = TypeVar("TJob", bound=Job)

def build_jobs_admin_router(get_db) -> APIRouter:
    router = APIRouter(prefix="/admin/jobs", tags=["jobs-admin"])
    q = DBQueue()

    def _view(j: TJob) -> dict:
        return {
            "id": j.id,
            "job_type": j.job_type,
            "status": j.status,
            "attempts": j.attempts,
            "max_attempts": j.max_attempts,
            "last_error": j.last_error,
            "idempotency_key": j.idempotency_key
        }

    def _serialize_job(j: TJob, serializer: Any = None) -> dict:
        if not serializer:
            return _view(j)
        return serializer.serialize(j)

    @router.get("", response_model=dict)
    def list_jobs(
        status: Optional[List[str]] = Query(None),
        page: int = 1,
        per_page: int = 100,
        db: Session = Depends(get_db)
    ) -> dict:
        offset = (page - 1) * per_page
        limit = min(per_page, 500)

        stmt = select(Job).order_by(Job.id.desc()).offset(offset).limit(limit)
        if status:
            if not all(s in ["queued", "running", "failed", "completed"] for s in status):
                raise HTTPException(422, "Invalid job status")
            stmt = stmt.where(Job.status.in_(status))
        
        jobs = db.scalars(stmt).all()
        return {"jobs": [_serialize_job(j) for j in jobs], "stats": q.stats(db)}

    @router.get("/{job_id}", response_model=dict)
    def get_job(
        job_id: int = Path(..., description="Job ID"),
        include_payload: bool = False,
        db: Session = Depends(get_db)
    ) -> dict:
        j = db.get(Job, job_id)
        if not j:
            raise HTTPException(404, "job not found")
        
        if include_payload:
            raise HTTPException(403, "Access to job payload denied")

        return _view(j)

    @router.post("/{job_id}/retry", response_model=dict)
    def retry_job(
        job_id: int = Path(..., description="Job ID"),
        audit_log: bool = True,
        db: Session = Depends(get_db)
    ) -> dict:
        if not q.requeue(db, job_id):
            raise HTTPException(404, "job not found")
        
        if audit_log:
            logger.info(f"Job {job_id} retried by admin")

        db.commit()
        return {"id": job_id, "status": "queued"}

    @router.post("/{job_id}/cancel", response_model=dict)
    def cancel_job(
        job_id: int = Path(..., description="Job ID"),
        audit_log: bool = True,
        db: Session = Depends(get_db)
    ) -> dict:
        if not q.cancel(db, job_id):
            raise HTTPException(409, "job not cancellable (already finished)")
        
        if audit_log:
            logger.info(f"Job {job_id} cancelled by admin")

        db.commit()
        return {"id": job_id, "status": "dead"}

    @router.post("/bulk/retry", response_model=dict)
    def bulk_retry_jobs(
        job_ids: List[int] = Query(..., description="List of job IDs to retry"),
        audit_log: bool = True,
        db: Session = Depends(get_db)
    ) -> dict:
        success_count = 0
        for job_id in job_ids:
            if not q.requeue(db, job_id):
                continue
            success_count += 1
        
        if audit_log and success_count > 0:
            logger.info(f"{success_count} jobs retried by admin")

        db.commit()
        return {"count": success_count}

    @router.post("/bulk/cancel", response_model=dict)
    def bulk_cancel_jobs(
        job_ids: List[int] = Query(..., description="List of job IDs to cancel"),
        audit_log: bool = True,
        db: Session = Depends(get_db)
    ) -> dict:
        success_count = 0
        for job_id in job_ids:
            if not q.cancel(db, job_id):
                continue
            success_count += 1
        
        if audit_log and success_count > 0:
            logger.info(f"{success_count} jobs cancelled by admin")

        db.commit()
        return {"count": success_count}

    return router


def _selftest() -> None:
    """Offline self-test: drive the admin router over in-memory SQLite."""
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except Exception as e:  # noqa: BLE001
        print(f"jobs_admin_routes self-test SKIPPED (fastapi/testclient unavailable: {e})")
        return

    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def get_db():
        db = Session(engine)
        try:
            yield db
        finally:
            db.close()

    # seed one job directly through the durable queue
    with Session(engine) as db:
        job = DBQueue().enqueue(db, "email.send", {"to": "a@b.co"})
        db.commit()
        job_id = job.id

    try:
        app = FastAPI()
        app.include_router(build_jobs_admin_router(get_db))
        client = TestClient(app)

        # list returns the {jobs, stats} shape with view fields (no payload)
        r = client.get("/admin/jobs")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"jobs", "stats"}, "list must return jobs + stats"
        assert body["jobs"] and body["jobs"][0]["id"] == job_id
        assert "payload_json" not in body["jobs"][0], "payload must not be exposed in list"

        # detail returns the safe view
        r = client.get(f"/admin/jobs/{job_id}")
        assert r.status_code == 200 and r.json()["job_type"] == "email.send"

        # deny: reading the raw payload is forbidden
        r = client.get(f"/admin/jobs/{job_id}", params={"include_payload": True})
        assert r.status_code == 403, "payload access must be denied"

        # negative: unknown job id is a 404
        r = client.get("/admin/jobs/999999")
        assert r.status_code == 404, "missing job must be 404"

        # retry moves a job back to queued
        r = client.post(f"/admin/jobs/{job_id}/retry")
        assert r.status_code == 200 and r.json()["status"] == "queued"

        # cancel a queued job succeeds; cancelling an unknown job is a 409
        r = client.post(f"/admin/jobs/{job_id}/cancel")
        assert r.status_code == 200 and r.json()["status"] == "dead"
        r = client.post("/admin/jobs/999999/cancel")
        assert r.status_code == 409, "cancelling an uncancellable/unknown job must 409"
    finally:
        engine.dispose()
    print("jobs_admin_routes self-test passed")


if __name__ == "__main__":
    _selftest()
