"""
logging_setup — Structured, JSON-capable logging with request correlation.

### PART-META-JSON
{
  "name": "logging_setup",
  "layer": "foundation",
  "purpose": "Structured logging bootstrap: JSON or text formatting, contextvar-based request correlation IDs and global log context, custom levels, audit hooks fired per record, in-process level metrics, log filtering/serialization/masking helpers, bulk emission, and rotating-file configuration.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Log level / format choices at startup; correlation IDs and context dicts at request time; log-record dicts for the filter/mask/serialize helpers.",
  "outputs": "Configured root logging, JSON log lines, filtered/masked/serialized record dicts.",
  "files_created": [],
  "security_notes": "mask_log exists precisely because log payloads may carry secrets — mask before shipping records to external sinks; masking is by exact key (recursively) and does not pattern-match values. Correlation IDs and log context are contextvar-scoped, so async tasks inherit them; never put credentials in set_log_context. configure_log_rotation writes to a caller-chosen path — keep it out of web-served directories.",
  "ai_usage": "Call setup_logging() once at startup; per request call add_correlation_id(logger, rid); use get_logger(__name__) everywhere else.",
  "example": "setup_logging(level='INFO', json_output=True); log = get_logger(__name__); log.info('ready')",
  "import_path": "scrapyard.foundation.logging_setup"
}
### END-PART-META
"""
from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, TypeVar

STATUS = "core"

T = TypeVar('T')

# --- contextvar-based correlation + context ---

_correlation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "scrapyard_correlation_id", default=None)
_log_context: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "scrapyard_log_context", default={})


class CorrelationIdFilter(logging.Filter):
    """Injects the contextvar correlation id + global log context into records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id") or record.request_id is None:  # type: ignore[attr-defined]
            record.request_id = _correlation_id.get()
        for key, value in _log_context.get().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        record.log_context = dict(_log_context.get())
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = getattr(record, "request_id", None)
        if rid:
            payload["request_id"] = rid
        context = getattr(record, "log_context", None)
        if context:
            payload.update(context)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure root logging once at startup. Idempotent."""
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler.addFilter(CorrelationIdFilter())
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class LoggerContextManager:
    """Temporarily set a correlation id and/or logger level:

        with LoggerContextManager(log, rid="req-1", level="DEBUG"):
            log.debug("traced")
    """

    def __init__(self, logger: logging.Logger, *, rid: Optional[str] = None,
                 level: Optional[str] = None):
        self.logger = logger
        self.rid = rid
        self.level = level
        self._rid_token: Optional[contextvars.Token] = None
        self._old_level: Optional[int] = None

    def __enter__(self) -> logging.Logger:
        if self.rid is not None:
            self._rid_token = _correlation_id.set(self.rid)
        if self.level is not None:
            self._old_level = self.logger.level
            self.logger.setLevel(self.level.upper())
        return self.logger

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._rid_token is not None:
            _correlation_id.reset(self._rid_token)
        if self._old_level is not None:
            self.logger.setLevel(self._old_level)


def add_correlation_id(logger: logging.Logger, rid: str) -> None:
    """Bind ``rid`` as the current correlation id (contextvar) and make sure the
    logger's records carry it (a CorrelationIdFilter is attached once)."""
    _correlation_id.set(rid)
    if not any(isinstance(f, CorrelationIdFilter) for f in logger.filters):
        logger.addFilter(CorrelationIdFilter())


def get_correlation_id() -> Optional[str]:
    return _correlation_id.get()


def clear_correlation_id() -> None:
    _correlation_id.set(None)


def set_custom_log_level(name: str, level: int) -> None:
    """Define a custom log level name (e.g. AUDIT=25, SECURITY=35)."""
    if not isinstance(level, int) or level <= 0:
        raise ValueError("level must be a positive integer")
    logging.addLevelName(level, name.upper())


def _level_number(level: str | int) -> int:
    if isinstance(level, int):
        return level
    value = logging.getLevelName(str(level).upper())
    if not isinstance(value, int):
        raise ValueError(f"Unknown log level: {level!r}")
    return value


def filter_logs(logs: List[Dict[str, Any]], min_level: str = "INFO",
                rid: Optional[str] = None) -> List[Dict[str, Any]]:
    """Filter record dicts by NUMERIC level threshold and optional request id."""
    min_level_num = _level_number(min_level)
    out = []
    for log in logs:
        try:
            level_num = _level_number(log.get("level", "NOTSET"))
        except ValueError:
            continue
        if level_num >= min_level_num and (not rid or log.get("request_id") == rid):
            out.append(log)
    return out


def serialize_log(log: Dict[str, Any], format: str = "json") -> str:
    """Serialize a log record dict for external systems (currently JSON)."""
    if format.lower() == "json":
        return json.dumps(log, default=str)
    raise ValueError(f"Unsupported format: {format}")


# --- audit hooks + metrics ---

_audit_hooks: List[Callable[[Dict[str, Any]], None]] = []
_log_metrics_counters: Dict[str, int] = {}


class _AuditHookHandler(logging.Handler):
    """Root-level handler that feeds every record to registered audit hooks."""

    def emit(self, record: logging.LogRecord) -> None:
        if not _audit_hooks:
            return
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        for hook in list(_audit_hooks):
            try:
                hook(payload)
            except Exception:  # a broken hook must never break logging
                pass


_audit_handler: Optional[_AuditHookHandler] = None


def register_audit_hook(hook: Callable[[Dict[str, Any]], None]) -> None:
    """Register a callable invoked with a payload dict for every emitted record."""
    global _audit_handler
    if not callable(hook):
        raise TypeError("hook must be callable")
    _audit_hooks.append(hook)
    if _audit_handler is None:
        _audit_handler = _AuditHookHandler(level=logging.NOTSET)
        _audit_handler.addFilter(CorrelationIdFilter())
        logging.getLogger().addHandler(_audit_handler)


def clear_audit_hooks() -> None:
    global _audit_handler
    _audit_hooks.clear()
    if _audit_handler is not None:
        logging.getLogger().removeHandler(_audit_handler)
        _audit_handler = None


def log_metrics(log: Dict[str, Any]) -> None:
    """Count records per level in-process; read back with get_log_metrics()."""
    level = str(log.get("level", "UNKNOWN")).upper()
    _log_metrics_counters[level] = _log_metrics_counters.get(level, 0) + 1


def get_log_metrics() -> Dict[str, int]:
    return dict(_log_metrics_counters)


def reset_log_metrics() -> None:
    _log_metrics_counters.clear()


def log_bulk(logs: List[Dict[str, Any]], format: str = "json") -> List[str]:
    """Serialize and emit multiple record dicts in one call; also feeds metrics.
    Returns the serialized lines."""
    logger = logging.getLogger("scrapyard.bulk")
    lines = []
    for log in logs:
        line = serialize_log(log, format)
        lines.append(line)
        log_metrics(log)
        logger.log(_level_number(log.get("level", "INFO")), "%s", line)
    return lines


def configure_log_rotation(max_bytes: int = 10_000_000, backup_count: int = 5,
                           log_file: str = "app.log") -> logging.Handler:
    """Attach a size-based RotatingFileHandler to the root logger. Replaces any
    rotation handler previously installed for the same file. Returns the handler."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, logging.handlers.RotatingFileHandler) and \
                getattr(h, "baseFilename", None) == logging.handlers.RotatingFileHandler(
                    log_file, delay=True).baseFilename:
            root.removeHandler(h)
            h.close()
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    handler.addFilter(CorrelationIdFilter())
    root.addHandler(handler)
    return handler


def mask_log(log: Dict[str, Any], mask_keys: List[str]) -> Dict[str, Any]:
    """Mask sensitive fields (recursively, by exact key) before output."""
    masked: Dict[str, Any] = {}
    for key, value in log.items():
        if key in mask_keys:
            masked[key] = "REDACTED"
        elif isinstance(value, dict):
            masked[key] = mask_log(value, mask_keys)
        else:
            masked[key] = value
    return masked


def set_log_context(context: Dict[str, Any]) -> None:
    """Merge fields into the contextvar log context included in all records."""
    merged = dict(_log_context.get())
    merged.update(context)
    _log_context.set(merged)


def clear_log_context() -> None:
    _log_context.set({})


def _selftest() -> None:
    import io
    import os
    import tempfile

    # setup + JSON output with correlation id + context
    setup_logging(level="DEBUG", json_output=True)
    root = logging.getLogger()
    buf = io.StringIO()
    root.handlers[0].stream = buf  # capture

    log = get_logger("selftest.logging")
    add_correlation_id(log, "req-123")  # no setCorrelationID call anywhere
    assert get_correlation_id() == "req-123"
    set_log_context({"tenant": "t-9"})
    log.info("hello")
    line = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert line["msg"] == "hello" and line["request_id"] == "req-123" and line["tenant"] == "t-9"
    clear_log_context()
    clear_correlation_id()

    # LoggerContextManager scopes rid and level, restoring after
    with LoggerContextManager(log, rid="scoped-1", level="ERROR") as scoped:
        assert get_correlation_id() == "scoped-1"
        assert scoped.level == logging.ERROR
    assert get_correlation_id() is None and log.level == logging.NOTSET

    # numeric level filtering (the old string comparison ordered DEBUG > CRITICAL)
    records = [
        {"level": "DEBUG", "msg": "d", "request_id": "a"},
        {"level": "INFO", "msg": "i", "request_id": "a"},
        {"level": "WARNING", "msg": "w", "request_id": "b"},
        {"level": "CRITICAL", "msg": "c", "request_id": "b"},
    ]
    assert [r["msg"] for r in filter_logs(records, "WARNING")] == ["w", "c"]
    assert [r["msg"] for r in filter_logs(records, "INFO", rid="a")] == ["i"]
    assert filter_logs([{"level": "NOT_A_LEVEL", "msg": "?"}], "DEBUG") == []
    try:
        filter_logs(records, "BOGUS")
        raise AssertionError("unknown min level accepted")
    except ValueError:
        pass

    # custom level registers and orders numerically
    set_custom_log_level("AUDIT", 25)
    assert logging.getLevelName(25) == "AUDIT"
    assert [r["msg"] for r in filter_logs(records + [{"level": "AUDIT", "msg": "a"}], "AUDIT")] == \
        ["w", "c", "a"]

    # serialization + masking
    s = serialize_log({"level": "INFO", "password": "hunter2"})
    assert json.loads(s)["password"] == "hunter2"
    masked = mask_log({"password": "x", "nested": {"token": "y", "ok": 1}, "keep": 2},
                      ["password", "token"])
    assert masked["password"] == "REDACTED" and masked["nested"]["token"] == "REDACTED"
    assert masked["keep"] == 2 and masked["nested"]["ok"] == 1
    try:
        serialize_log({}, format="yaml")
        raise AssertionError("unsupported format accepted")
    except ValueError:
        pass

    # audit hooks fire per record
    seen: list = []
    register_audit_hook(lambda payload: seen.append(payload["msg"]))
    log.warning("audited-event")
    assert "audited-event" in seen
    clear_audit_hooks()
    log.warning("not-audited")
    assert "not-audited" not in seen

    # metrics + bulk
    reset_log_metrics()
    lines = log_bulk([{"level": "INFO", "msg": "b1"}, {"level": "ERROR", "msg": "b2"}])
    assert len(lines) == 2 and get_log_metrics() == {"INFO": 1, "ERROR": 1}

    # rotation writes to file
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "rot.log")
        handler = configure_log_rotation(max_bytes=100_000, backup_count=2, log_file=path)
        log.info("rotated-line")
        handler.flush()
        with open(path, encoding="utf-8") as f:
            assert "rotated-line" in f.read()
        logging.getLogger().removeHandler(handler)
        handler.close()

    # restore a sane default so later imports aren't stuck on a StringIO
    setup_logging(level="INFO", json_output=False)
    print("logging_setup selftest: PASS")


if __name__ == "__main__":
    _selftest()
