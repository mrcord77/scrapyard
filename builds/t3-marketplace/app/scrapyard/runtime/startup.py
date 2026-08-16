"""Bootstrap a fully-wired, self-contained application.

A generated `main.py` calls `bootstrap(...)` and exposes the result as `app`,
so `uvicorn main:app` boots the whole stack: settings -> database -> middleware
-> routers -> startup/shutdown hooks -> health.

### PART-META-JSON
{
  "name": "startup",
  "layer": "runtime",
  "purpose": "One-call application bootstrap for generated apps: loads settings, runs the fallback honesty gate, initializes the database (including library security tables), builds the FastAPI app with lifespan hooks and security headers, and exposes runtime objects on app.state; plus helpers for health probes, extra lifespan hooks, custom error handlers, environment validation, and a runtime posture summary.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi",
    "sqlalchemy"
  ],
  "inputs": "Router list, a declarative models Base, optional Hooks registry / security capability list / flags.",
  "outputs": "A fully wired FastAPI app (settings, engine, hooks, security_caps on app.state).",
  "files_created": [],
  "security_notes": "bootstrap() runs the fallbacks production gate BEFORE serving: in production it refuses to start while reference crypto, console email, offline LLM, or per-process limiter/cache paths are active. Security response headers are installed by default (install_headers=True) — disabling them is an explicit caller choice. The database is verified reachable and migrated at boot, so a misconfigured app fails at startup rather than on first request.",
  "ai_usage": "app = bootstrap(routers=[...], models_base=Base); then optionally register_health_probes(app) / register_lifespan_hooks(app, ...).",
  "example": "app = bootstrap(routers=generated_routers, models_base=Base, title='my-app')",
  "import_path": "scrapyard.runtime.startup"
}
### END-PART-META
"""
from __future__ import annotations

STATUS = "core"

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("scrapyard.runtime.startup")

VALID_ENVIRONMENTS = ("development", "staging", "production")


def bootstrap(*, routers, models_base, require_encryption: bool = False,
              title: str = "scrapyard-app", hooks=None, install_headers: bool = True,
              security_caps=None):
    from scrapyard.runtime.settings import load_settings
    from scrapyard.runtime.database import init_database
    from scrapyard.runtime.lifespan import Hooks, make_lifespan
    from scrapyard.api.app_factory import create_app

    settings = load_settings(require_encryption=require_encryption)
    hooks = hooks or Hooks()

    # honesty gate: name the local-only fallbacks actually active, and in
    # production refuse to start if any forbidden one (reference crypto, console
    # email, offline LLM) is live — presence is never silently mistaken for prod.
    from scrapyard.runtime.fallbacks import detect_fallbacks, assert_no_forbidden_fallbacks
    detect_fallbacks(settings)
    assert_no_forbidden_fallbacks(settings.app_env)

    # init engine, generated tables, AND the library security tables the routes use
    engine = init_database(settings, models_base, security_caps=security_caps)

    @hooks.on_startup
    def _bind_db():
        init_database(settings, models_base, security_caps=security_caps)

    @hooks.on_shutdown
    def _dispose_db():
        try:
            engine.dispose()
        except Exception:
            pass

    app = create_app(title=title, settings=settings, routers=routers,
                     lifespan=make_lifespan(hooks))
    if install_headers:
        from scrapyard.security.security_headers import install_security_headers
        install_security_headers(app)

    # expose runtime objects for verification/probes
    app.state.settings = settings
    app.state.engine = engine
    app.state.hooks = hooks
    app.state.security_caps = list(security_caps or [])
    return app


# -- optional post-bootstrap configuration (all operate on a passed app) ----------
@dataclass
class HealthProbeConfig:
    liveness_path: str = "/health/liveness"
    readiness_path: str = "/health/readiness"
    readiness_check: Optional[Callable[[], bool]] = None


@dataclass
class ErrorHandlersConfig:
    http_error_handlers: Dict[int, Callable] = field(default_factory=dict)
    application_error_handlers: Dict[type, Callable] = field(default_factory=dict)


def validate_app_environment(app_env: str) -> str:
    if app_env not in VALID_ENVIRONMENTS:
        raise ValueError(
            f"invalid app environment {app_env!r}; expected one of {VALID_ENVIRONMENTS}")
    return app_env


def register_lifespan_hooks(app, startup: Optional[List[Callable]] = None,
                            shutdown: Optional[List[Callable]] = None) -> None:
    """Attach extra hooks to the Hooks registry bootstrap() stored on app.state."""
    hooks = getattr(app.state, "hooks", None)
    if hooks is None:
        raise RuntimeError("app was not built by bootstrap(); no hooks registry")
    for fn in startup or []:
        hooks.on_startup(fn)
    for fn in shutdown or []:
        hooks.on_shutdown(fn)


def register_health_probes(app, config: Optional[HealthProbeConfig] = None) -> None:
    cfg = config or HealthProbeConfig()

    def _liveness():
        return {"status": "alive"}

    def _readiness():
        if cfg.readiness_check is not None and not cfg.readiness_check():
            from fastapi.responses import JSONResponse
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return {"status": "ready"}

    app.add_api_route(cfg.liveness_path, _liveness, methods=["GET"])
    app.add_api_route(cfg.readiness_path, _readiness, methods=["GET"])


def setup_error_handlers(app, config: ErrorHandlersConfig) -> None:
    for status_code, handler in config.http_error_handlers.items():
        app.add_exception_handler(status_code, handler)
    for exception_type, handler in config.application_error_handlers.items():
        app.add_exception_handler(exception_type, handler)


def describe_app(app) -> Dict[str, Any]:
    """Runtime posture summary for admin/status surfaces."""
    settings = getattr(app.state, "settings", None)
    return {
        "title": getattr(app, "title", None),
        "env": getattr(settings, "app_env", None) if settings else None,
        "routes": len(getattr(app, "routes", [])),
        "security_caps": list(getattr(app.state, "security_caps", [])),
        "hooks": (app.state.hooks.get_metrics()
                  if hasattr(getattr(app.state, "hooks", None), "get_metrics")
                  else None),
    }


def _selftest() -> None:
    import os

    from fastapi.testclient import TestClient
    from sqlalchemy import Integer, String
    from sqlalchemy.orm import DeclarativeBase, mapped_column

    # environment validation
    for env in VALID_ENVIRONMENTS:
        assert validate_app_environment(env) == env
    try:
        validate_app_environment("qa")
        raise AssertionError("invalid environment accepted")
    except ValueError:
        pass

    class Base(DeclarativeBase):
        pass

    class Note(Base):
        __tablename__ = "runtime_startup_notes"
        id = mapped_column(Integer, primary_key=True)
        text = mapped_column(String(100))

    saved = {k: os.environ.get(k) for k in ("APP_ENV", "DATABASE_URL")}
    try:
        os.environ["APP_ENV"] = "development"
        os.environ.pop("DATABASE_URL", None)

        # full bootstrap smoke: dev, sqlite, no routers
        app = bootstrap(routers=[], models_base=Base, title="startup-selftest")
        assert app.title == "startup-selftest"
        assert app.state.settings.dev and app.state.engine is not None
        assert app.state.security_caps == []

        # extra lifespan hooks attach to the bootstrap registry
        fired: list = []
        register_lifespan_hooks(app, startup=[lambda: fired.append("up")],
                                shutdown=[lambda: fired.append("down")])

        # health probes + custom error handler
        cfg = HealthProbeConfig(readiness_check=lambda: True)
        register_health_probes(app, cfg)

        class TeapotError(Exception):
            pass

        async def teapot_handler(request, exc):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "teapot"}, status_code=418)

        setup_error_handlers(app, ErrorHandlersConfig(
            application_error_handlers={TeapotError: teapot_handler}))

        @app.get("/boom")
        def boom():
            raise TeapotError()

        with TestClient(app) as client:
            assert client.get("/health/liveness").json() == {"status": "alive"}
            assert client.get("/health/readiness").json() == {"status": "ready"}
            assert client.get("/boom").status_code == 418
            # security headers were installed by default
            r = client.get("/health/liveness")
            assert "X-Content-Type-Options" in r.headers
        assert "up" in fired and "down" in fired

        # not-ready path
        app2 = bootstrap(routers=[], models_base=Base, title="s2", install_headers=False)
        register_health_probes(app2, HealthProbeConfig(readiness_check=lambda: False))
        with TestClient(app2) as client:
            assert client.get("/health/readiness").status_code == 503

        # describe_app posture summary
        d = describe_app(app)
        assert d["title"] == "startup-selftest" and d["env"] == "development"
        assert d["routes"] > 0 and isinstance(d["hooks"], dict)

        # register_lifespan_hooks demands a bootstrap()-built app
        from fastapi import FastAPI
        try:
            register_lifespan_hooks(FastAPI(), startup=[lambda: None])
            raise AssertionError("non-bootstrap app accepted")
        except RuntimeError:
            pass
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # bootstrap's sqlite dev file may have been created next to cwd; leave it
        # alone if it pre-existed, remove if we made it.

    print("runtime.startup selftest: PASS")


if __name__ == "__main__":
    _selftest()
