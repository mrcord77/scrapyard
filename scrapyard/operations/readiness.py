"""
readiness — Deep readiness checks + a fail-closed /readyz endpoint.

Liveness (/healthz, /livez) answers "is the process up?". Readiness answers "can it
actually serve?" — which requires its dependencies to be usable AND its schema to be
current. An app whose migrations are behind head is NOT ready (it would read/write an
out-of-date schema), so /readyz returns 503 until migrations are applied.

### PART-META-JSON
{
  "name": "readiness",
  "layer": "operations",
  "purpose": "Deep readiness probe (DB + Redis + migration state) with a fail-closed /readyz.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "DATABASE_URL, optional REDIS_URL, the app's alembic config.",
  "outputs": "A readiness report; GET /readyz -> 200 ready / 503 not-ready.",
  "files_created": [],
  "security_notes": "Detail strings avoid secrets. 503 keeps an unready instance out of a load balancer rotation.",
  "ai_usage": "mount build_readiness_router(resolver) where resolver()->readiness_report(...)",
  "example": "from scrapyard.operations.readiness import readiness_report, build_readiness_router",
  "import_path": "scrapyard.operations.readiness"
}
### END-PART-META
"""
from __future__ import annotations

STATUS = "core"


def check_database(url: str):
    try:
        from sqlalchemy import create_engine, text
        eng = create_engine(url)
        try:
            with eng.connect() as c:
                c.execute(text("SELECT 1"))
        finally:
            eng.dispose()
        return True, "reachable"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"[:140]


def check_redis(url: str):
    try:
        import redis
        r = redis.Redis.from_url(url)
        return bool(r.ping()), "reachable"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"[:140]


def check_migrations(database_url: str, alembic_ini: str, script_location: str):
    """Ready only when the DB's applied revision equals the migration head."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine
    cfg = Config(alembic_ini)
    cfg.set_main_option("script_location", script_location)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    eng = create_engine(database_url)
    try:
        with eng.connect() as c:
            current = MigrationContext.configure(c).get_current_revision()
    finally:
        eng.dispose()
    return (current == head), f"current={current} head={head}"


def readiness_report(*, database_url=None, redis_url=None,
                     alembic_ini=None, script_location=None) -> dict:
    checks: dict[str, dict] = {}
    ready = True
    if database_url:
        ok, detail = check_database(database_url)
        checks["database"] = {"ok": ok, "detail": detail}
        ready = ready and ok
        if alembic_ini and script_location:
            try:
                mok, mdetail = check_migrations(database_url, alembic_ini, script_location)
            except Exception as e:  # noqa: BLE001
                mok, mdetail = False, f"{type(e).__name__}: {e}"[:140]
            checks["migrations"] = {"ok": mok, "detail": mdetail}
            ready = ready and mok
    if redis_url:
        ok, detail = check_redis(redis_url)
        checks["redis"] = {"ok": ok, "detail": detail}
        ready = ready and ok
    return {"ready": bool(ready), "checks": checks}


def build_readiness_router(resolver):
    """resolver() -> readiness_report(...) dict. Mounts GET /readyz (200/503)."""
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse
    router = APIRouter()

    @router.get("/readyz")
    def readyz():  # noqa: ANN202
        report = resolver()
        return JSONResponse(report, status_code=200 if report.get("ready") else 503)

    return router


def _selftest() -> None:
    """Offline self-test: probe aggregation + fail-closed /readyz status codes."""
    # a reachable DB (in-memory sqlite) reports ready
    rep = readiness_report(database_url="sqlite:///:memory:")
    assert rep["ready"] is True, "reachable DB must be ready"
    assert rep["checks"]["database"]["ok"] is True

    # negative: an unreachable DB drives the whole report not-ready (fail closed)
    bad = readiness_report(database_url="postgresql://u:p@127.0.0.1:1/none")
    assert bad["ready"] is False, "unreachable DB must make the app not-ready"
    assert bad["checks"]["database"]["ok"] is False

    # no dependencies configured -> vacuously ready
    assert readiness_report()["ready"] is True

    # router: 200 when ready, 503 when not (the load-balancer gate)
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except Exception as e:  # noqa: BLE001
        print(f"readiness self-test passed (router check SKIPPED: {e})")
        return

    app = FastAPI()
    app.include_router(build_readiness_router(lambda: {"ready": True, "checks": {}}))
    assert TestClient(app).get("/readyz").status_code == 200, "ready must be 200"

    app2 = FastAPI()
    app2.include_router(build_readiness_router(lambda: {"ready": False, "checks": {}}))
    assert TestClient(app2).get("/readyz").status_code == 503, "not-ready must be 503"
    print("readiness self-test passed")


if __name__ == "__main__":
    _selftest()
