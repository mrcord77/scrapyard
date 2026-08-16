"""
error_taxonomy — Canonical app error classes mapped to HTTP + codes.

### PART-META-JSON
{
  "name": "error_taxonomy",
  "layer": "foundation",
  "purpose": "Shared error vocabulary for the whole stack: canonical error codes (validation_error, unauthorized, forbidden, not_found, conflict, rate_limited, payment_required, internal) mapped to HTTP status + default message, with status_for/message_for lookups that fall back to 500/internal for unknown codes.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Canonical error-code strings.",
  "outputs": "HTTP status ints and safe default messages.",
  "files_created": [],
  "security_notes": "Default messages are deliberately generic (no internal detail), so handlers that fall back to message_for never leak stack or schema information to clients. Unknown codes resolve to 500/'Internal error' rather than raising, keeping the error path itself exception-safe.",
  "ai_usage": "In error handlers: return JSONResponse(status_code=status_for(code), content={'code': code, 'detail': message_for(code)}).",
  "example": "status_for('not_found')  # 404",
  "import_path": "scrapyard.foundation.error_taxonomy"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

# Canonical error codes -> (http status, default message). The api/error_handling
# part maps AppError subclasses; this is the shared vocabulary.
ERROR_CODES = {
    "validation_error": (422, "Request failed validation"),
    "unauthorized": (401, "Authentication required"),
    "forbidden": (403, "Not permitted"),
    "not_found": (404, "Resource not found"),
    "conflict": (409, "Conflicting state"),
    "rate_limited": (429, "Too many requests"),
    "payment_required": (402, "Payment required"),
    "internal": (500, "Internal error"),
}

def status_for(code: str) -> int:
    return ERROR_CODES.get(code, ERROR_CODES["internal"])[0]

def message_for(code: str) -> str:
    return ERROR_CODES.get(code, ERROR_CODES["internal"])[1]


def _selftest() -> None:
    assert status_for("not_found") == 404 and message_for("not_found") == "Resource not found"
    assert status_for("validation_error") == 422
    assert status_for("unauthorized") == 401 and status_for("forbidden") == 403
    assert status_for("conflict") == 409 and status_for("rate_limited") == 429
    assert status_for("payment_required") == 402
    # unknown codes fall back to internal/500, never raise
    assert status_for("no_such_code") == 500
    assert message_for("no_such_code") == "Internal error"
    # every entry is (int status in range, non-empty generic message)
    for code, (status, msg) in ERROR_CODES.items():
        assert isinstance(status, int) and 400 <= status <= 599, code
        assert isinstance(msg, str) and msg, code
    print("error_taxonomy selftest: PASS")


if __name__ == "__main__":
    _selftest()
