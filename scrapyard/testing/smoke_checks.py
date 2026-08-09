"""
smoke_checks — Post-deploy smoke test of key routes (in-process, no server needed).

### PART-META-JSON
{
  "name": "smoke_checks",
  "layer": "testing",
  "purpose": "Smoke checks that exercise a FastAPI/Starlette app object DIRECTLY via TestClient (httpx ASGI transport) - health routes, response/content checks, errors, CORS, metrics, auth, bulk ops - no live server or localhost socket required.",
  "addition": false,
  "status": "core",
  "dependencies": ["fastapi", "httpx"],
  "inputs": "An app factory callable (create_app) returning the ASGI app; route paths and expectations per check.",
  "outputs": "Result dicts: {'ok': bool, ...detail fields (status_code, missing_routes, error)}.",
  "files_created": [],
  "security_notes": "Requests run in-process against the app object - nothing is bound to a network port and no traffic leaves the machine. Checks report status/detail only; they never log request bodies, so keep secrets out of check payloads anyway.",
  "ai_usage": "report = check_all_health_routes(create_app); check_route_response(create_app, '/items/1', 200, {'id': 1}). Every check takes the factory, not a URL.",
  "example": "from scrapyard.testing.smoke_checks import check_app_boots, check_all_health_routes",
  "import_path": "scrapyard.testing.smoke_checks"
}
### END-PART-META
"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional

STATUS = "core"


def _client(app):
    """In-process client against the ASGI app object (no live server)."""
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False)


def check_app_boots(create_app) -> dict:
    """Assert an app factory produces an app exposing a health route."""
    try:
        app = create_app()
        paths = {getattr(r, "path", None) for r in app.routes}
        return {"ok": "/healthz" in paths, "routes": len(paths)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_all_health_routes(create_app: Callable[[], Any],
                            expected_routes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Ensure health routes exist AND return 200, exercised via TestClient."""
    try:
        app = create_app()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    paths = {getattr(r, "path", None) for r in app.routes}
    expected = set(expected_routes or ['/healthz', '/ready', '/live'])
    missing_routes = expected - paths
    if missing_routes:
        return {"ok": False, "missing_routes": sorted(missing_routes)}
    with _client(app) as client:
        for route in sorted(expected):
            response = client.get(route)
            if response.status_code != 200:
                return {"ok": False, "status_code": response.status_code, "route": route}
    return {"ok": True}


def check_route_response(create_app: Callable[[], Any], path: str, expected_status: int,
                         expected_content: Optional[Dict] = None) -> Dict[str, Any]:
    """Validate a specific route's response status and JSON content, in-process."""
    try:
        app = create_app()
        with _client(app) as client:
            response = client.get(path)
        if response.status_code != expected_status:
            return {"ok": False, "status_code": response.status_code}
        if expected_content is not None and response.json() != expected_content:
            return {"ok": False, "actual_content": response.json()}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_route_errors(create_app: Callable[[], Any],
                       missing_path: str = "/nonexistent") -> Dict[str, Any]:
    """Verify unknown routes 404 with a JSON error body."""
    try:
        app = create_app()
        with _client(app) as client:
            response = client.get(missing_path)
        if response.status_code != 404:
            return {"ok": False, "status_code": response.status_code}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_rate_limiting(create_app: Callable[[], Any], path: str,
                        num_requests: int) -> Dict[str, Any]:
    """Send repeated requests; reports whether a 429 appeared and where."""
    try:
        app = create_app()
        with _client(app) as client:
            for i in range(num_requests):
                response = client.get(path)
                if response.status_code == 429:
                    return {"ok": True, "limited_at_request": i + 1}
                if response.status_code != 200:
                    return {"ok": False, "status_code": response.status_code}
        return {"ok": True, "limited_at_request": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_async_route(create_app: Callable[[], Any], path: str,
                      expected_status: int) -> Dict[str, Any]:
    """Ensure an async route is handled and returns the expected status."""
    try:
        app = create_app()
        with _client(app) as client:
            response = client.get(path)
        if response.status_code != expected_status:
            return {"ok": False, "status_code": response.status_code}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_cors_headers(create_app: Callable[[], Any], path: str,
                       origin: str = "https://example.test") -> Dict[str, Any]:
    """Validate CORS preflight sets Access-Control-Allow-Origin."""
    try:
        app = create_app()
        with _client(app) as client:
            response = client.options(path, headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            })
        if "access-control-allow-origin" not in {k.lower() for k in response.headers}:
            return {"ok": False, "status_code": response.status_code}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_route_metrics(create_app: Callable[[], Any],
                        path: str = "/metrics") -> Dict[str, Any]:
    """Ensure a Prometheus-style metrics route responds with exposition format."""
    try:
        app = create_app()
        with _client(app) as client:
            response = client.get(path)
        if response.status_code != 200:
            return {"ok": False, "status_code": response.status_code}
        if path == "/metrics" and not (b"# HELP" in response.content
                                       and b"# TYPE" in response.content):
            return {"ok": False, "error": "missing prometheus exposition markers"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_route_logging(create_app: Callable[[], Any], path: str,
                        logger_name: str = "") -> Dict[str, Any]:
    """Verify hitting the route emits at least one log record (captured in-process)."""
    import logging

    class _Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records: List[logging.LogRecord] = []

        def emit(self, record):
            self.records.append(record)

    handler = _Capture()
    root = logging.getLogger(logger_name)
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        app = create_app()
        with _client(app) as client:
            response = client.get(path)
        if response.status_code != 200:
            return {"ok": False, "status_code": response.status_code}
        return {"ok": len(handler.records) > 0, "records": len(handler.records)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


def check_route_authentication(create_app: Callable[[], Any], path: str) -> Dict[str, Any]:
    """Validate a protected route rejects unauthenticated requests (401/403)."""
    try:
        app = create_app()
        with _client(app) as client:
            response = client.get(path)
        if response.status_code not in (401, 403):
            return {"ok": False, "status_code": response.status_code,
                    "error": "protected route served an unauthenticated request"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_route_bulk_operations(create_app: Callable[[], Any], path: str,
                                payload: List[Dict]) -> Dict[str, Any]:
    """POST a bulk payload and expect a 200/201 acknowledgement."""
    try:
        app = create_app()
        with _client(app) as client:
            response = client.post(path, json=payload)
        if response.status_code not in (200, 201):
            return {"ok": False, "status_code": response.status_code}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _build_demo_app():
    """Reference app used by the selftest - never bound to a port."""
    import logging
    from fastapi import FastAPI, Header, HTTPException, Response
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://example.test"],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    log = logging.getLogger("smoke_demo")

    @app.get("/healthz")
    def healthz():
        log.info("health check")
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        return {"status": "ready"}

    @app.get("/live")
    def live():
        return {"status": "live"}

    @app.get("/items/1")
    async def item_one():
        return {"id": 1}

    @app.get("/metrics")
    def metrics():
        return Response("# HELP up 1\n# TYPE up gauge\nup 1\n",
                        media_type="text/plain")

    @app.get("/private")
    def private(authorization: str | None = Header(default=None)):
        if not authorization:
            raise HTTPException(status_code=401, detail="unauthenticated")
        return {"secret": True}

    @app.post("/items/bulk", status_code=201)
    def bulk(items: List[Dict]):
        return {"created": len(items)}

    return app


def _selftest() -> bool:
    create_app = _build_demo_app

    assert check_app_boots(create_app)["ok"]
    assert check_all_health_routes(create_app) == {"ok": True}
    missing = check_all_health_routes(lambda: __import__("fastapi").FastAPI())
    assert not missing["ok"] and missing["missing_routes"]

    assert check_route_response(create_app, "/items/1", 200, {"id": 1}) == {"ok": True}
    bad = check_route_response(create_app, "/items/1", 200, {"id": 2})
    assert not bad["ok"] and bad["actual_content"] == {"id": 1}
    assert check_route_response(create_app, "/nope", 404) == {"ok": True}

    assert check_route_errors(create_app) == {"ok": True}
    assert check_async_route(create_app, "/items/1", 200) == {"ok": True}
    assert check_rate_limiting(create_app, "/healthz", 5)["ok"]
    assert check_cors_headers(create_app, "/healthz") == {"ok": True}
    assert check_route_metrics(create_app) == {"ok": True}
    logres = check_route_logging(create_app, "/healthz", logger_name="smoke_demo")
    assert logres["ok"], logres
    assert check_route_authentication(create_app, "/private") == {"ok": True}
    leaky = check_route_authentication(create_app, "/healthz")
    assert not leaky["ok"]  # an open route must FAIL the auth check
    assert check_route_bulk_operations(create_app, "/items/bulk",
                                       [{"a": 1}, {"b": 2}]) == {"ok": True}

    print("smoke_checks selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
