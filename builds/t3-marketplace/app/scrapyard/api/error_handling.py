"""
error_handling — Exception handlers producing consistent error envelopes.

### PART-META-JSON
{
  "name": "error_handling",
  "layer": "api",
  "purpose": "Typed application errors (AppError + NotFound/Unauthorized/Forbidden/Conflict/ValidationFailed) rendered as a consistent JSON envelope {error: {code, message, details?}}, and install_error_handlers wiring them plus a catch-all 500 handler onto a FastAPI app.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "AppError subclasses raised anywhere in route/service code.",
  "outputs": "JSON error envelopes with the subclass's status code; generic 500 for uncaught exceptions.",
  "files_created": [],
  "security_notes": "The catch-all handler returns a fixed generic message for uncaught exceptions — stack traces and internal exception text never reach clients. AppError messages ARE returned verbatim, so raise them with client-safe wording only and keep secrets/PII out of message and details.",
  "ai_usage": "raise NotFound('order not found') in services; install_error_handlers(app) once at app build (app_factory already does).",
  "example": "raise Conflict('slot already reserved', details={'slot_id': 7})",
  "import_path": "scrapyard.api.error_handling"
}
### END-PART-META
"""
from __future__ import annotations
from typing import Any

STATUS = "core"


class AppError(Exception):
    """Base application error -> consistent JSON envelope."""
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, code: str | None = None,
                 status_code: int | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details

    def envelope(self) -> dict:
        body = {"error": {"code": self.code, "message": self.message}}
        if self.details is not None:
            body["error"]["details"] = self.details
        return body


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


def install_error_handlers(app) -> None:
    """Attach handlers to a FastAPI app for AppError + uncaught exceptions."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(AppError)
    async def _app_error(_req: Request, exc: AppError):  # noqa: ANN202
        return JSONResponse(status_code=exc.status_code, content=exc.envelope())

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception):  # noqa: ANN202
        return JSONResponse(status_code=500,
                            content={"error": {"code": "internal_error", "message": "Internal server error"}})


def _selftest() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # envelope construction
    e = Conflict("slot taken", details={"slot": 7})
    assert e.status_code == 409 and e.code == "conflict"
    assert e.envelope() == {"error": {"code": "conflict", "message": "slot taken",
                                      "details": {"slot": 7}}}
    plain = AppError("boom")
    assert plain.status_code == 500 and "details" not in plain.envelope()["error"]
    override = AppError("odd", code="teapot", status_code=418)
    assert override.status_code == 418 and override.code == "teapot"
    for cls, status in ((NotFound, 404), (Unauthorized, 401), (Forbidden, 403),
                        (Conflict, 409), (ValidationFailed, 422)):
        assert cls("m").status_code == status

    # wired into an app: AppError envelope + catch-all masking
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/missing")
    def missing():
        raise NotFound("thing not found")

    @app.get("/crash")
    def crash():
        raise RuntimeError("db password is hunter2")  # must never surface

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/missing")
        assert r.status_code == 404
        assert r.json()["error"] == {"code": "not_found", "message": "thing not found"}
        r = client.get("/crash")
        assert r.status_code == 500
        assert r.json() == {"error": {"code": "internal_error",
                                      "message": "Internal server error"}}
        assert "hunter2" not in r.text

    print("error_handling selftest: PASS")


if __name__ == "__main__":
    _selftest()
