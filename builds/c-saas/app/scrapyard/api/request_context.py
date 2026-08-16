"""
request_context — Per-request ID + context var propagated to logs.

### PART-META-JSON
{
  "name": "request_context",
  "layer": "api",
  "purpose": "Per-request correlation: middleware that adopts an incoming X-Request-ID (or mints a uuid4 hex), stores it in a contextvar readable anywhere via current_request_id(), resets it after the request, and echoes it back on the response.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Optional client-supplied X-Request-ID header.",
  "outputs": "x-request-id response header; contextvar available to logging/error reporting.",
  "files_created": [],
  "security_notes": "Client-supplied request IDs are adopted verbatim for trace continuity — treat them as untrusted display data in logs/dashboards (no HTML rendering without escaping) and never use them as keys for authorization or storage. The contextvar is reset per request, so IDs cannot bleed between concurrent requests.",
  "ai_usage": "install_request_context(app) once (app_factory does this); call current_request_id() in log/error code.",
  "example": "install_request_context(app); logger.info('handled', extra={'rid': current_request_id()})",
  "import_path": "scrapyard.api.request_context"
}
### END-PART-META
"""
from contextvars import ContextVar, Token
import uuid
from typing import Any, Callable, Dict, List, Optional
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

STATUS = "core"

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

def current_request_id() -> str:
    return _request_id.get()


def install_request_context(app: FastAPI) -> None:
    """Middleware that assigns/propagates an X-Request-ID and exposes it to logs."""
    class _Mw(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Callable) -> Any:
            rid = request.headers.get("x-request-id") or uuid.uuid4().hex
            token: Token[str] = _request_id.set(rid)
            try:
                response = await call_next(request)
            finally:
                _request_id.reset(token)
            response.headers["x-request-id"] = rid
            return response

    app.add_middleware(_Mw)


def _selftest() -> None:
    from fastapi.testclient import TestClient

    app = FastAPI()
    install_request_context(app)
    seen: dict = {}

    @app.get("/ctx")
    def ctx():
        seen["rid"] = current_request_id()
        return {"rid": current_request_id()}

    with TestClient(app) as client:
        # minted id: response header matches what the handler saw
        r = client.get("/ctx")
        rid = r.headers["x-request-id"]
        assert len(rid) == 32 and r.json()["rid"] == rid == seen["rid"]

        # client-supplied id is adopted and echoed
        r = client.get("/ctx", headers={"X-Request-ID": "trace-abc-123"})
        assert r.headers["x-request-id"] == "trace-abc-123"
        assert r.json()["rid"] == "trace-abc-123"

        # two requests get distinct minted ids
        a = client.get("/ctx").headers["x-request-id"]
        b = client.get("/ctx").headers["x-request-id"]
        assert a != b

    # outside a request the contextvar is reset to the default
    assert current_request_id() == "-"
    print("request_context selftest: PASS")


if __name__ == "__main__":
    _selftest()
