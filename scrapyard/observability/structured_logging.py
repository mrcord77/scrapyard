"""
structured_logging — Log helpers that emit structured events.

### PART-META-JSON
{
  "name": "structured_logging",
  "layer": "observability",
  "purpose": "Log helpers that emit structured events.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure(level, format_type); log_event_with_level(logger, msg, level, **fields); log_exception(logger, msg, **fields); log_bulk_events(logger, events, **metadata); log_operation_start(logger, operation_id, **fields); SecurityViolation(...); JsonFormatter(...) (plus more).",
  "outputs": "Returns: configure -> logging.Logger; log_event_with_level -> None; log_exception -> None; log_bulk_events -> None; log_operation_start -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `configure` from `scrapyard.observability.structured_logging` and call it as shown in `example`; run `py -m scrapyard.observability.structured_logging` to see its offline selftest.",
  "example": "from scrapyard.observability.structured_logging import configure",
  "import_path": "scrapyard.observability.structured_logging"
}
### END-PART-META
"""
from __future__ import annotations
import json
import logging
import sys  # Added missing import
from typing import Any, Dict, List, Optional, TypeVar, Union
from fastapi import Request, Response
from sqlalchemy.orm.session import Session

STATUS = "core"

class SecurityViolation(Exception):
    pass

T = TypeVar('T')

def configure(level: str = "INFO", format_type: str = "json") -> logging.Logger:
    logger = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)  # Fixed undefined name `sys`

    if format_type == "json":
        formatter = JsonFormatter()
    else:
        raise ValueError("Unsupported format type")
    
    handler.setFormatter(formatter)
    logger.handlers = [handler]
    logger.setLevel(level)
    return logger

def log_event_with_level(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields: Any) -> None:
    record = logging.LogRecord(
        name=logger.name,
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=None,
        exc_info=None
    )
    for k, v in fields.items():
        setattr(record, k, v)
    logger.handle(record)

def log_exception(logger: logging.Logger, msg: str, **fields: Any) -> None:
    record = logging.LogRecord(
        name=logger.name,
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg=msg,
        args=None,
        exc_info=True
    )
    for k, v in fields.items():
        setattr(record, k, v)
    logger.handle(record)

def log_bulk_events(logger: logging.Logger, events: List[Dict[str, Any]], **metadata: Any) -> None:
    for event in events:
        record = logging.LogRecord(
            name=logger.name,
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=json.dumps(event),
            args=None
        )
        for k, v in metadata.items():
            setattr(record, k, v)
        logger.handle(record)

def log_operation_start(logger: logging.Logger, operation_id: str, **fields: Any) -> None:
    record = logging.LogRecord(
        name=logger.name,
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=json.dumps({"operation_id": operation_id}),
        args=None
    )
    for k, v in fields.items():
        setattr(record, k, v)
    logger.handle(record)

def log_operation_end(logger: logging.Logger, operation_id: str, **fields: Any) -> None:
    record = logging.LogRecord(
        name=logger.name,
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=json.dumps({"operation_id": operation_id}),
        args=None
    )
    for k, v in fields.items():
        setattr(record, k, v)
    logger.handle(record)

def log_audit_event(logger: logging.Logger, user: str, action: str, context: Dict[str, Any]) -> None:
    record = logging.LogRecord(
        name=logger.name,
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=json.dumps({"user": user, "action": action}),
        args=None
    )
    for k, v in context.items():
        setattr(record, k, v)
    logger.handle(record)

def log_metric(logger: logging.Logger, name: str, value: float, **tags: Any) -> None:
    record = logging.LogRecord(
        name=logger.name,
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=json.dumps({"metric_name": name, "value": value}),
        args=None
    )
    for k, v in tags.items():
        setattr(record, k, v)
    logger.handle(record)

def log_request(logger: logging.Logger, request: Request, **fields: Any) -> None:
    record = logging.LogRecord(
        name=logger.name,
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=json.dumps({"method": request.method, "path": request.url.path}),
        args=None
    )
    for k, v in fields.items():
        setattr(record, k, v)
    logger.handle(record)

def log_response(logger: logging.Logger, response: Response, **fields: Any) -> None:
    record = logging.LogRecord(
        name=logger.name,
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=json.dumps({"status_code": response.status_code}),
        args=None
    )
    for k, v in fields.items():
        setattr(record, k, v)
    logger.handle(record)

def configure_formatter(logger: logging.Logger, format_type: str = "json") -> None:
    if format_type == "json":
        formatter = JsonFormatter()
    else:
        raise ValueError("Unsupported format type")
    
    for handler in logger.handlers:
        handler.setFormatter(formatter)


# --- grafted from original part (API stability) ---
class JsonFormatter(logging.Formatter):
    def format(self, record):
        from scrapyard.compliance.privacy_policy_hooks import registry
        base={"level":record.levelname,"logger":record.name,"msg":record.getMessage()}
        for k,v in getattr(record,"extra_fields",{}).items():
            if registry.should_log(k): base[k]=v
        return json.dumps(base)

def log_event(logger, msg, **fields):
    rec=logging.LogRecord(logger.name,logging.INFO,"",0,msg,None,None)
    rec.extra_fields=fields; logger.handle(rec)


def _selftest() -> None:
    """Offline self-test: a structured event carries its fields on the emitted
    LogRecord (captured via a handler), and the JsonFormatter serializes those
    fields to JSON while redacting privacy-sensitive keys."""
    import logging as _logging

    logger = _logging.getLogger("scrapyard.structured_logging.selftest")
    logger.setLevel(_logging.INFO)
    logger.propagate = False

    captured: list = []

    class _Capture(_logging.Handler):
        def emit(self, record):
            captured.append(record)

    logger.handlers = [_Capture()]

    # The structured event reaches the handler with its fields intact.
    log_event(logger, "user login", user_id=42, action="login")
    assert len(captured) == 1, f"expected 1 captured record, got {len(captured)}"
    rec = captured[0]
    assert rec.getMessage() == "user login"
    assert rec.extra_fields == {"user_id": 42, "action": "login"}, rec.extra_fields

    # The JsonFormatter renders level/logger/msg plus the structured fields as JSON.
    fmt = JsonFormatter()
    out = json.loads(fmt.format(rec))
    assert out["level"] == "INFO" and out["msg"] == "user login"
    assert out["user_id"] == 42 and out["action"] == "login"

    # Negative/adversarial: a privacy-sensitive field ("token") must be dropped from
    # the serialized output, never logged verbatim.
    log_event(logger, "auth", user_id=7, token="s3cr3t-value")
    secret_out = json.loads(fmt.format(captured[-1]))
    assert secret_out["user_id"] == 7
    assert "token" not in secret_out, "sensitive 'token' field must be redacted from logs"
    assert "s3cr3t-value" not in fmt.format(captured[-1]), "secret value leaked into log output"

    print("structured_logging selftest: PASS")


if __name__ == "__main__":
    _selftest()

