"""
app_scaffold — Minimal application entrypoint wiring config+logging+app_factory.

### PART-META-JSON
{
  "name": "app_scaffold",
  "layer": "foundation",
  "purpose": "One-call production-shaped app assembly: builds the FastAPI app via api.app_factory (logging, request context, error handlers, health), installs security headers, and optionally CORS for an explicit origin list. Does not create database tables — schema management belongs to migrations.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Optional title, settings object (.debug/.log_level/.log_json), router list, CORS origin allow-list.",
  "outputs": "A configured FastAPI application.",
  "files_created": [],
  "security_notes": "Security response headers (CSP, HSTS, nosniff, frame-deny) are always installed — there is no flag to skip them here. CORS is enabled only when an explicit origins list is passed; no wildcard default. The scaffold deliberately never calls create_all(): production schemas come from migrations, so a misconfigured DB fails loudly instead of being silently created.",
  "ai_usage": "app = production_app(title='svc', settings=get_settings(), routers=[api_router], cors_origins=['https://app.example.com']).",
  "example": "app = production_app(title='svc', routers=[router])",
  "import_path": "scrapyard.foundation.app_scaffold"
}
### END-PART-META
"""
from __future__ import annotations

STATUS = "core"


def production_app(*, title="app", settings=None, routers=None, cors_origins=None):
    """Assemble a production-shaped app: logging, security headers, CORS, routers.
    Does NOT create tables (use migrations in prod)."""
    from scrapyard.api.app_factory import create_app
    from scrapyard.security.security_headers import install_security_headers
    app = create_app(title=title, settings=settings, routers=routers)
    install_security_headers(app)
    if cors_origins:
        from scrapyard.security.cors import install_cors
        install_cors(app, origins=cors_origins)
    return app


def _selftest() -> None:
    from fastapi import APIRouter
    from fastapi.testclient import TestClient

    router = APIRouter()

    @router.get("/hello")
    def hello():
        return {"hi": True}

    app = production_app(title="scaffold-selftest", routers=[router],
                         cors_origins=["https://app.example.test"])
    assert app.title == "scaffold-selftest"

    with TestClient(app) as client:
        r = client.get("/hello")
        assert r.status_code == 200 and r.json() == {"hi": True}
        # security headers installed
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert "Content-Security-Policy" in r.headers
        # health endpoints from app_factory are wired
        assert client.get("/livez").status_code == 200 and client.get("/healthz").status_code == 200
        # CORS answers preflight for the allow-listed origin only
        pre = client.options("/hello", headers={
            "Origin": "https://app.example.test",
            "Access-Control-Request-Method": "GET"})
        assert pre.headers.get("access-control-allow-origin") == "https://app.example.test"
        pre_bad = client.options("/hello", headers={
            "Origin": "https://evil.example.test",
            "Access-Control-Request-Method": "GET"})
        assert pre_bad.headers.get("access-control-allow-origin") is None

    # without cors_origins no CORS middleware is added
    app2 = production_app(title="no-cors")
    with TestClient(app2) as client:
        r = client.get("/livez", headers={"Origin": "https://app.example.test"})
        assert "access-control-allow-origin" not in r.headers

    print("app_scaffold selftest: PASS")


if __name__ == "__main__":
    _selftest()
