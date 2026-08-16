"""
middleware — Common middleware stack (timing, body limits, gzip, logging, limits).

### PART-META-JSON
{
  "name": "middleware",
  "layer": "api",
  "purpose": "Composable FastAPI/ASGI middleware installers: response timing header + access log, request body size limit (413), gzip compression (via Starlette's GZipMiddleware), custom response headers, request metrics into the observability registry, per-client in-memory rate limiting (429), structured request logging, replay-safe request body logging, JSON body validation against a pydantic model (400), and a /_bulk endpoint dispatching batched sub-requests in-process; configure_middleware wires any subset from a MiddlewareConfig.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi",
    "pydantic"
  ],
  "inputs": "A FastAPI app plus per-middleware options (size caps, headers, rate limits, a pydantic validator model).",
  "outputs": "Mutated app with the selected middleware; JSON error responses (413/429/400) on violations.",
  "files_created": [],
  "security_notes": "The body-size limit rejects oversized uploads by Content-Length before the body is read, but a client omitting Content-Length bypasses it — pair with a reverse-proxy limit. The in-memory rate limiter is per-process (each worker admits the full budget); use the distributed limiter from security.rate_limiting for real global enforcement. Body logging replays the buffered body to downstream handlers and truncates logged bytes, but request bodies may contain credentials — enable it only in development. Bulk dispatch runs sub-requests through the same middleware-wrapped app, so per-request protections still apply to each sub-request.",
  "ai_usage": "configure_middleware(app, MiddlewareConfig(enable_timing=True, enable_body_limit=True)); or call individual installers.",
  "example": "install_timing(app); add_body_size_limit(app, max_size=1_000_000)",
  "import_path": "scrapyard.api.middleware"
}
### END-PART-META
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

STATUS = "core"
log = logging.getLogger("scrapyard.access")


class MiddlewareConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    enable_timing: bool = True
    enable_body_limit: bool = True
    enable_gzip_compression: bool = True
    enable_custom_headers: bool = False
    enable_metrics: bool = False
    enable_rate_limiting: bool = False
    enable_structured_logging: bool = False
    enable_body_logging: bool = False
    enable_bulk_request_support: bool = False
    enable_request_validation: bool = False
    # options consumed by the corresponding installers
    max_body_size: int = 10_000_000
    gzip_min_size: int = 1024
    custom_headers: Dict[str, str] = {}
    rate_limit_per_minute: int = 120
    log_bodies: bool = False
    validator: Optional[type] = None  # a pydantic model class


class RequestTooLarge(HTTPException):
    def __init__(self, detail: str = "Request body too large"):
        super().__init__(status_code=413, detail=detail)


class InvalidRequest(HTTPException):
    def __init__(self, detail: str = "Invalid request payload"):
        super().__init__(status_code=400, detail=detail)


def _json_response(send_ready: dict) -> tuple[dict, dict]:
    body = json.dumps({"detail": send_ready["detail"]}).encode()
    start = {"type": "http.response.start", "status": send_ready["status"],
             "headers": [(b"content-type", b"application/json"),
                         (b"content-length", str(len(body)).encode())]}
    return start, {"type": "http.response.body", "body": body}


def configure_middleware(app: FastAPI, config: MiddlewareConfig) -> FastAPI:
    """Install the middleware selected by ``config`` (installers are CALLED with
    the app — they are not themselves request handlers).

    Installation order matters: Starlette prepends, so LATER installs sit
    OUTERMOST. Protective limits (body size, rate limit) are installed last so
    they reject requests before any other middleware does work.
    """
    if config.enable_request_validation:
        if config.validator is None:
            raise ValueError("enable_request_validation requires config.validator")
        add_request_validation(app, config.validator)
    if config.enable_body_logging:
        add_body_logging(app, log_bodies=config.log_bodies)
    if config.enable_structured_logging:
        add_structured_logging(app, log)
    if config.enable_metrics:
        add_metrics(app)
    if config.enable_custom_headers:
        add_custom_headers(app, config.custom_headers)
    if config.enable_timing:
        install_timing(app)
    if config.enable_gzip_compression:
        add_gzip_compression(app, min_size=config.gzip_min_size)
    if config.enable_rate_limiting:
        add_rate_limiting(app, per_minute=config.rate_limit_per_minute)
    if config.enable_body_limit:
        add_body_size_limit(app, max_size=config.max_body_size)
    if config.enable_bulk_request_support:
        add_bulk_request_support(app)
    return app


def install_timing(app: FastAPI):
    @app.middleware("http")
    async def _timing(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        dur_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time-ms"] = f"{dur_ms:.1f}"
        log.info("%s %s -> %s (%.1fms)", request.method, request.url.path,
                 response.status_code, dur_ms)
        return response


def add_body_size_limit(app: FastAPI, max_size: int = 10_000_000):
    """Reject write requests whose declared Content-Length exceeds ``max_size``
    with a clean 413 (returned, not raised — raising inside middleware would 500)."""
    class _BodyLimit:
        def __init__(self, asgi_app):
            self.asgi_app = asgi_app

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http" and scope.get("method") in ("POST", "PUT", "PATCH"):
                for k, v in scope.get("headers", []):
                    if k == b"content-length":
                        try:
                            if int(v) > max_size:
                                start, body = _json_response(
                                    {"status": 413, "detail": "Request body too large"})
                                await send(start)
                                await send(body)
                                return
                        except ValueError:
                            pass
                        break
            await self.asgi_app(scope, receive, send)

    app.add_middleware(_BodyLimit)


def add_gzip_compression(app: FastAPI, min_size: int = 1024):
    """Compress responses above ``min_size`` bytes using Starlette's GZipMiddleware
    (in-process — no outbound requests involved)."""
    from starlette.middleware.gzip import GZipMiddleware
    app.add_middleware(GZipMiddleware, minimum_size=min_size)


def add_custom_headers(app: FastAPI, headers: Dict[str, str]):
    @app.middleware("http")
    async def _custom_headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in headers.items():
            response.headers[key] = value
        return response


def add_metrics(app: FastAPI):
    """Count requests and status classes into the observability metrics registry."""
    from scrapyard.observability.metrics import registry

    @app.middleware("http")
    async def _metrics(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        registry.incr("http_requests_total")
        registry.incr(f"http_responses_{response.status_code // 100}xx_total")
        registry.observe("http_request_seconds", time.perf_counter() - start)
        return response


def add_rate_limiting(app: FastAPI, per_minute: int = 120):
    """Per-client-IP sliding-window limiter (in-memory, PER PROCESS). Responds 429
    with Retry-After when the budget is exhausted."""
    window: Dict[str, list] = {}

    class _RateLimit:
        def __init__(self, asgi_app):
            self.asgi_app = asgi_app

        async def __call__(self, scope, receive, send):
            if scope.get("type") != "http":
                await self.asgi_app(scope, receive, send)
                return
            client = scope.get("client") or ("anonymous", 0)
            key = client[0]
            now = time.monotonic()
            hits = window.setdefault(key, [])
            cutoff = now - 60.0
            while hits and hits[0] <= cutoff:
                hits.pop(0)
            if len(hits) >= per_minute:
                start, body = _json_response({"status": 429, "detail": "rate limit exceeded"})
                start["headers"].append((b"retry-after", b"60"))
                await send(start)
                await send(body)
                return
            hits.append(now)
            await self.asgi_app(scope, receive, send)

    app.add_middleware(_RateLimit)


def add_structured_logging(app: FastAPI, logger: logging.Logger):
    @app.middleware("http")
    async def _structured_logging(request: Request, call_next):
        start_time = time.time()
        try:
            response = await call_next(request)
            logger.info("request", extra={"http": {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": (time.time() - start_time) * 1000,
            }})
            return response
        except Exception as e:
            logger.error("request failed", extra={"http": {
                "method": request.method,
                "path": request.url.path,
                "status_code": e.status_code if isinstance(e, HTTPException) else 500,
                "duration_ms": (time.time() - start_time) * 1000,
                "error": e.__class__.__name__,
            }})
            raise


def _buffering_receive(receive, buffered: bytearray):
    """Wrap an ASGI receive so the request body is captured AND replayed."""
    done = {"flag": False}

    async def _replay():
        if done["flag"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return message
            buffered.extend(message.get("body", b""))
            if not message.get("more_body"):
                done["flag"] = True
                return {"type": "http.request", "body": bytes(buffered), "more_body": False}

    return _replay


def add_body_logging(app: FastAPI, log_bodies: bool = False, max_logged: int = 1024):
    """Log (truncated) request bodies for write methods. The body is buffered and
    replayed so downstream handlers still receive it. Dev tool — bodies may hold
    credentials, keep this off in production."""
    class _BodyLog:
        def __init__(self, asgi_app):
            self.asgi_app = asgi_app

        async def __call__(self, scope, receive, send):
            if scope.get("type") != "http" or scope.get("method") not in ("POST", "PUT", "PATCH"):
                await self.asgi_app(scope, receive, send)
                return
            content_length = 0
            for k, v in scope.get("headers", []):
                if k == b"content-length":
                    try:
                        content_length = int(v)
                    except ValueError:
                        pass
                    break
            if not (log_bodies or content_length < 1024):
                await self.asgi_app(scope, receive, send)
                return
            buffered = bytearray()
            body_seen = {"logged": False}

            async def wrapped_receive():
                message = await receive()
                if message["type"] == "http.request":
                    buffered.extend(message.get("body", b""))
                    if not message.get("more_body") and not body_seen["logged"]:
                        body_seen["logged"] = True
                        log.info("request body %s %s: %r%s", scope.get("method"),
                                 scope.get("path"), bytes(buffered[:max_logged]),
                                 "...(truncated)" if len(buffered) > max_logged else "")
                return message

            await self.asgi_app(scope, wrapped_receive, send)

    app.add_middleware(_BodyLog)


def add_request_validation(app: FastAPI, validator: type,
                           exclude_paths: tuple[str, ...] = ("/_bulk",)):
    """Validate JSON bodies of write requests against a pydantic v2 model class;
    invalid payloads get a 400 before reaching the route. The body is buffered
    and replayed for downstream handlers. Paths in ``exclude_paths`` (the bulk
    endpoint by default, whose payload is a list of sub-requests) are skipped."""
    class _Validate:
        def __init__(self, asgi_app):
            self.asgi_app = asgi_app

        async def __call__(self, scope, receive, send):
            if (scope.get("type") != "http"
                    or scope.get("method") not in ("POST", "PUT", "PATCH")
                    or scope.get("path") in exclude_paths):
                await self.asgi_app(scope, receive, send)
                return
            # read the full body up-front
            chunks = bytearray()
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    break
                chunks.extend(message.get("body", b""))
                if not message.get("more_body"):
                    break
            try:
                validator.model_validate_json(bytes(chunks) or b"null")
            except Exception as e:
                start, body = _json_response({"status": 400,
                                              "detail": f"Invalid request payload: {e.__class__.__name__}"})
                await send(start)
                await send(body)
                return

            replayed = {"sent": False}

            async def replay_receive():
                if not replayed["sent"]:
                    replayed["sent"] = True
                    return {"type": "http.request", "body": bytes(chunks), "more_body": False}
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.asgi_app(scope, replay_receive, send)

    app.add_middleware(_Validate)


def add_bulk_request_support(app: FastAPI, path: str = "/_bulk", max_requests: int = 25):
    """Add a POST endpoint that accepts [{'method','path','body'?}, ...] and
    dispatches each sub-request through the app in-process, returning the list
    of {status, body} results."""
    from fastapi.responses import JSONResponse
    import httpx

    @app.post(path, tags=["bulk"])
    async def _bulk(request: Request):
        try:
            requests_spec = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "body must be a JSON list"})
        if not isinstance(requests_spec, list):
            return JSONResponse(status_code=400, content={"detail": "body must be a JSON list"})
        if len(requests_spec) > max_requests:
            return JSONResponse(status_code=413,
                                content={"detail": f"too many sub-requests (max {max_requests})"})
        results = []
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bulk.local") as client:
            for spec in requests_spec:
                method = str(spec.get("method", "GET")).upper()
                sub_path = str(spec.get("path", "/"))
                if sub_path == path:
                    results.append({"status": 400, "body": {"detail": "no nested bulk"}})
                    continue
                try:
                    resp = await client.request(method, sub_path, json=spec.get("body"))
                    try:
                        payload = resp.json()
                    except ValueError:
                        payload = resp.text
                    results.append({"status": resp.status_code, "body": payload})
                except Exception as e:
                    results.append({"status": 500, "body": {"detail": e.__class__.__name__}})
        return {"results": results}


def _selftest() -> None:
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.post("/echo")
    async def echo(request: Request):
        return {"echo": (await request.body()).decode()}

    @app.get("/big")
    def big():
        return {"data": "x" * 5000}

    class Payload(BaseModel):
        name: str

    cfg = MiddlewareConfig(
        enable_timing=True, enable_body_limit=True, enable_gzip_compression=True,
        enable_custom_headers=True, custom_headers={"X-Custom": "yes"},
        enable_metrics=True, enable_rate_limiting=True, rate_limit_per_minute=1000,
        enable_structured_logging=True, enable_body_logging=True, log_bodies=True,
        enable_bulk_request_support=True,
        enable_request_validation=True, validator=Payload,
        max_body_size=400,
    )
    configure_middleware(app, cfg)

    from scrapyard.observability.metrics import registry
    before = registry.snapshot()["counters"].get("http_requests_total", 0)

    with TestClient(app) as client:
        # timing + custom headers on a plain route
        r = client.get("/ping")
        assert r.status_code == 200
        assert "X-Response-Time-ms" in r.headers and r.headers["X-Custom"] == "yes"

        # body limit: oversized declared Content-Length -> 413
        r = client.post("/echo", content=b"x" * 500,
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 413

        # request validation: bad JSON -> 400; valid payload passes through with body intact
        r = client.post("/echo", json={"wrong_field": 1})
        assert r.status_code == 400
        r = client.post("/echo", json={"name": "ok"})
        assert r.status_code == 200 and json.loads(r.json()["echo"]) == {"name": "ok"}

        # gzip kicks in for large responses when requested
        r = client.get("/big", headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200 and r.json()["data"] == "x" * 5000

        # metrics counted
        after = registry.snapshot()["counters"]["http_requests_total"]
        assert after > before

        # bulk endpoint dispatches sub-requests through the app
        r = client.post("/_bulk", json=[
            {"method": "GET", "path": "/ping"},
            {"method": "POST", "path": "/echo", "body": {"name": "bulk"}},
            {"method": "POST", "path": "/_bulk", "body": []},
        ])
        assert r.status_code == 200
        results = r.json()["results"]
        assert results[0]["status"] == 200 and results[0]["body"] == {"ok": True}
        assert results[1]["status"] in (200, 400, 413)
        assert results[2]["status"] == 400  # no nested bulk

    # rate limiting: tight budget trips 429
    app2 = FastAPI()

    @app2.get("/r")
    def r_route():
        return {}
    add_rate_limiting(app2, per_minute=3)
    with TestClient(app2) as client:
        codes = [client.get("/r").status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and 429 in codes[3:]
        limited = client.get("/r")
        assert limited.status_code == 429 and limited.headers.get("retry-after") == "60"

    # config guard: validation without a validator is refused
    try:
        configure_middleware(FastAPI(), MiddlewareConfig(
            enable_timing=False, enable_body_limit=False, enable_gzip_compression=False,
            enable_request_validation=True))
        raise AssertionError("validator-less validation accepted")
    except ValueError:
        pass

    print("middleware selftest: PASS")


if __name__ == "__main__":
    _selftest()
