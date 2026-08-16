"""
domain_errors — typed domain-rule violations + their HTTP handlers.

Generated services raise these when a *business rule* is violated (an ineligible or
non-existent reference, an overlapping reservation, an illegal/blocked state
transition) — as opposed to a raw DB integrity error. The app factory installs
handlers so they surface as a clean 409 instead of an unhandled 500.

### PART-META-JSON
{
  "name": "domain_errors",
  "layer": "api",
  "purpose": "Typed domain-rule violations (reference/conflict/workflow) and their 409 handlers.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Public API: install_domain_error_handlers(app); WorkflowError(...); DomainRuleError(...).",
  "outputs": "Returns: install_domain_error_handlers -> None.",
  "files_created": [],
  "security_notes": "Error messages are domain-level and safe to return; do not embed secrets/PII in rule errors.",
  "ai_usage": "Generated services raise WorkflowError / DomainRuleError; the app factory calls install_domain_error_handlers(app).",
  "example": "from scrapyard.api.domain_errors import DomainRuleError, WorkflowError, install_domain_error_handlers",
  "import_path": "scrapyard.api.domain_errors"
}
### END-PART-META
"""
from __future__ import annotations

STATUS = "core"


class WorkflowError(Exception):
    """A state transition is not allowed, or a transition guard (same-row or
    cross-entity) failed."""


class DomainRuleError(Exception):
    """A create violated a domain rule: a referenced row does not exist or is not
    in an eligible status, or it would overlap an existing active reservation."""


def install_domain_error_handlers(app) -> None:
    """Register 409 handlers for the domain-rule exception types on a FastAPI app."""
    from fastapi.responses import JSONResponse

    @app.exception_handler(DomainRuleError)
    async def _domain_rule(_request, exc):  # noqa: ANN001, ANN202
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(WorkflowError)
    async def _workflow(_request, exc):  # noqa: ANN001, ANN202
        return JSONResponse(status_code=409, content={"detail": str(exc)})


def _selftest() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    install_domain_error_handlers(app)

    @app.get("/rule")
    def rule():
        raise DomainRuleError("referenced row is not eligible")

    @app.get("/workflow")
    def workflow():
        raise WorkflowError("transition draft->archived is not allowed")

    with TestClient(app) as client:
        r = client.get("/rule")
        assert r.status_code == 409
        assert r.json() == {"detail": "referenced row is not eligible"}
        r = client.get("/workflow")
        assert r.status_code == 409
        assert "not allowed" in r.json()["detail"]

    # both are plain Exception subclasses services can raise without fastapi
    assert issubclass(DomainRuleError, Exception) and issubclass(WorkflowError, Exception)
    print("domain_errors selftest: PASS")


if __name__ == "__main__":
    _selftest()
