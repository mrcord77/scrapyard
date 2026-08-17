"""
app_factory — FastAPI application factory wiring middleware, errors, health.

### PART-META-JSON
{
  "name": "app_factory",
  "layer": "api",
  "purpose": "FastAPI application factory: configures logging from settings, installs request-id context, consistent error envelopes, domain-rule and DB-integrity 409 handlers, health endpoints (/livez, /healthz, /health), and mounts caller-provided routers with optional lifespan hooks.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi",
    "sqlalchemy"
  ],
  "inputs": "Optional title, settings object (.debug/.log_level/.log_json), APIRouter list, lifespan factory.",
  "outputs": "A configured FastAPI application with health + error handling wired.",
  "files_created": [],
  "security_notes": "IntegrityError and uncaught exceptions are mapped to fixed generic messages (409/500) so constraint names, SQL, and stack traces never reach clients. debug=True (from settings) enables FastAPI debug tracebacks — never set it in production. Health endpoints are unauthenticated by design; keep probe names free of sensitive topology or wrap them behind your ingress.",
  "ai_usage": "app = create_app(title='svc', settings=settings, routers=[my_router]); uvicorn serves it directly.",
  "example": "app = create_app(routers=[users_router])",
  "import_path": "scrapyard.api.app_factory"
}
### END-PART-META
"""
from __future__ import annotations

STATUS = "core"


def create_app(*, title: str = "scrapyard-app", settings=None, routers=None, lifespan=None):
    """Build a FastAPI app with request-id, error handlers, and health wired.

    Pass any object with .debug/.log_level/.log_json (e.g. foundation.config.Settings)
    as ``settings`` to configure logging; defaults are safe. Pass ``routers`` (a list
    of APIRouter) to mount additional routers, e.g. generated model routes. Pass
    ``lifespan`` (an async context manager factory) to run startup/shutdown hooks.
    """
    from fastapi import FastAPI
    from scrapyard.foundation.logging_setup import setup_logging
    from scrapyard.foundation.health import health, liveness
    from scrapyard.api.error_handling import install_error_handlers
    from scrapyard.api.request_context import install_request_context

    setup_logging(getattr(settings, "log_level", "INFO"), getattr(settings, "log_json", False))
    app = FastAPI(title=title, debug=getattr(settings, "debug", False), lifespan=lifespan)
    install_request_context(app)
    install_error_handlers(app)

    # Referential-integrity / uniqueness violations (e.g. a create that references a
    # non-existent parent row) surface as a clean 409, not an unhandled 500.
    from fastapi.responses import JSONResponse
    from sqlalchemy.exc import IntegrityError

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_request, _exc):  # noqa: ANN001, ANN202
        return JSONResponse(status_code=409, content={
            "detail": "constraint violation: a referenced record does not exist, "
                      "or a uniqueness constraint failed"})

    # domain-rule violations (ineligible reference, overlap, illegal transition) -> 409
    from scrapyard.api.domain_errors import install_domain_error_handlers
    install_domain_error_handlers(app)

    @app.get("/livez", tags=["health"])
    def _livez():  # noqa: ANN202
        return liveness()

    @app.get("/healthz", tags=["health"])
    async def _healthz():  # noqa: ANN202
        return await health.report()

    @app.get("/health", tags=["health"])  # alias of /healthz for tool/user compatibility
    async def _health():  # noqa: ANN202
        return await health.report()

    for r in (routers or []):
        app.include_router(r)

    return app


def _selftest() -> None:
    from fastapi import APIRouter
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import IntegrityError

    from scrapyard.api.domain_errors import DomainRuleError
    from scrapyard.api.error_handling import NotFound

    router = APIRouter()

    @router.get("/thing")
    def thing():
        return {"thing": 1}

    @router.get("/missing")
    def missing():
        raise NotFound("nope")

    @router.get("/integrity")
    def integrity():
        raise IntegrityError("INSERT INTO secret_table ...", {}, Exception("dup key"))

    @router.get("/rule")
    def rule():
        raise DomainRuleError("ineligible reference")

    lifecycle: list = []

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        lifecycle.append("start")
        yield
        lifecycle.append("stop")

    app = create_app(title="factory-selftest", routers=[router], lifespan=lifespan)
    assert app.title == "factory-selftest"

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/thing").json() == {"thing": 1}
        # request-id middleware wired
        assert "x-request-id" in client.get("/thing").headers
        # health endpoints
        assert client.get("/livez").json() == {"status": "alive"}
        for path in ("/healthz", "/health"):
            body = client.get(path).json()
            assert "status" in body and "checks" in body
        # error envelope handlers
        r = client.get("/missing")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
        # integrity errors -> generic 409, no SQL leak
        r = client.get("/integrity")
        assert r.status_code == 409 and "secret_table" not in r.text
        # domain rule errors -> 409 with domain message
        r = client.get("/rule")
        assert r.status_code == 409 and r.json()["detail"] == "ineligible reference"
    assert lifecycle == ["start", "stop"]

    print("app_factory selftest: PASS")


if __name__ == "__main__":
    _selftest()
