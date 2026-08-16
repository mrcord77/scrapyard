"""
admin_routes — Operational admin API: live status and job-queue visibility.

### PART-META-JSON
{
  "name": "admin_routes",
  "layer": "admin",
  "purpose": "Operational admin endpoints: /admin/status (live counts + fallback posture) and /admin/jobs (durable queue stats).",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi",
    "sqlalchemy"
  ],
  "inputs": "build_admin_router(get_db): GET /admin/status, GET /admin/jobs.",
  "outputs": "Live operational status (table counts, active local-only fallbacks) and job-queue stats.",
  "files_created": [],
  "security_notes": "Exposes operational data — gate behind admin authorization (permissions/admin_access) before mounting in production; the router does not self-enforce admin. /admin/status reports counts and the active-fallback posture (so an operator can see if reference crypto / console email are live); it does not leak secrets. /admin/jobs reflects the durable queue only — reports disabled honestly if db_queue isn't in the build.",
  "ai_usage": "router = build_admin_router(get_db); mount under an admin-authorized prefix. Reports degrade honestly when optional subsystems (users table, db_queue) aren't present.",
  "example": "from scrapyard.admin.admin_routes import build_admin_router; app.include_router(build_admin_router(get_db))",
  "import_path": "scrapyard.admin.admin_routes"
}
### END-PART-META
"""
from __future__ import annotations

STATUS = "core"


def build_admin_router(get_db):
    from fastapi import APIRouter, Depends

    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.get("/status")
    def status(db=Depends(get_db)):
        """Live operational status: counts for whatever tables exist, plus the
        active local-only fallback posture. Each probe is best-effort so a missing
        optional table degrades to omission, not a 500."""
        out = {"ok": True, "checks": {}}
        try:
            from scrapyard.identity.users import User
            out["checks"]["users"] = db.query(User).count()
        except Exception:
            pass
        try:
            from scrapyard.admin.audit_logs import AuditLog, verify_chain
            out["checks"]["audit_entries"] = db.query(AuditLog).count()
            out["checks"]["audit_chain_ok"] = verify_chain(db)["ok"]
        except Exception:
            pass
        try:
            from scrapyard.runtime.fallbacks import active
            out["fallbacks_active"] = sorted(active().keys())
        except Exception:
            out["fallbacks_active"] = []
        return out

    @router.get("/jobs")
    def jobs(db=Depends(get_db)):
        """Durable job-queue stats — honestly disabled if db_queue isn't included."""
        try:
            from scrapyard.jobs.db_queue import DBQueue
            return {"enabled": True, "stats": DBQueue().stats(db)}
        except Exception:
            return {"enabled": False, "reason": "db_queue not included in this build"}

    return router


def _selftest() -> None:
    """Offline self-test: mount the router and exercise both endpoints."""
    import os
    import tempfile
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from scrapyard.database.base_model import Base
    from scrapyard.identity.users import User
    import scrapyard.admin.audit_logs  # noqa: F401
    from scrapyard.admin.audit_logs import record

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as seed:
                seed.add(User(email="a@example.com", password_hash="h"))
                record(seed, action="boot", actor_user_id=None, target="system")
                seed.commit()

            def get_db():
                db = Session(engine)
                try:
                    yield db
                finally:
                    db.close()

            app = FastAPI()
            app.include_router(build_admin_router(get_db))
            client = TestClient(app)

            r = client.get("/admin/status")
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            assert body["checks"]["users"] == 1
            assert body["checks"]["audit_entries"] == 1
            assert body["checks"]["audit_chain_ok"] is True
            assert isinstance(body["fallbacks_active"], list)

            r = client.get("/admin/jobs")
            assert r.status_code == 200
            assert "enabled" in r.json()
        finally:
            engine.dispose()
    print("admin_routes self-test passed")


if __name__ == "__main__":
    _selftest()
