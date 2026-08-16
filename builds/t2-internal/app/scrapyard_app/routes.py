"""Generated route wiring: always /health + /capabilities, plus selected routers."""
from __future__ import annotations
import os
from fastapi import FastAPI
from scrapyard_app.settings import settings
from scrapyard_app.capabilities import CAPABILITIES

_mounted: list = []
_skipped: list = []


def include_routes(app: FastAPI):
    # /health, /healthz, /livez come from the app factory (one canonical payload for
    # every generated app, assemble or EOS). Routes adds deep readiness + capabilities.
    # Deep readiness: DB reachable + migrations at head (+ Redis if configured).
    # Returns 503 until ready, so a load balancer keeps the instance out of rotation.
    try:
        from scrapyard.operations.readiness import readiness_report, build_readiness_router
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        def _resolver():
            ini = os.path.join(_root, "alembic.ini")
            sl = os.path.join(_root, "migrations")
            uses_redis = (os.environ.get("CACHE_BACKEND", "").lower() == "redis"
                          or os.environ.get("RATE_LIMIT_BACKEND", "").lower() == "redis")
            return readiness_report(
                database_url=settings.database_url,
                redis_url=os.environ.get("REDIS_URL") if uses_redis else None,
                alembic_ini=ini if os.path.exists(ini) else None,
                script_location=sl if os.path.exists(sl) else None)

        app.include_router(build_readiness_router(_resolver))
    except Exception as _e:  # readiness is best-effort wiring; never block boot
        @app.get("/readyz", tags=["health"])
        def _readyz():
            return {"ready": True, "checks": {}, "note": f"readiness unavailable: {_e}"}

    @app.get("/capabilities", tags=["meta"])
    def capabilities():
        return {**CAPABILITIES, "routers_mounted": _mounted, "routers_skipped": _skipped}

    # scrapyard.admin.admin_routes (required)
    try:
        from scrapyard.admin.admin_routes import build_admin_router as _factory
        from scrapyard.database.db_session import get_db
        from scrapyard.runtime.request_security import make_scoped_db
        from scrapyard_app.settings import settings as _s
        app.include_router(_factory(make_scoped_db(get_db, _s.database_url)))
        _mounted.append('/admin' or 'scrapyard.admin.admin_routes')
    except Exception as exc:
        if True:
            raise RuntimeError(f"required router scrapyard.admin.admin_routes failed to mount: {exc}")
        _skipped.append(('scrapyard.admin.admin_routes', str(exc)))
        print(f"[routes] skipped scrapyard.admin.admin_routes (dev, optional): {exc}")
    return app
