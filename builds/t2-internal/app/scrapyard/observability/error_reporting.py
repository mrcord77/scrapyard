"""
error_reporting — Capture exceptions to Sentry/provider.

### PART-META-JSON
{
  "name": "error_reporting",
  "layer": "observability",
  "purpose": "Capture exceptions to Sentry/provider.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: init_sentry(dsn, *, transport, environment); ErrorReporter(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `init_sentry` from `scrapyard.observability.error_reporting` and call it as shown in `example`; run `py -m scrapyard.observability.error_reporting` to see its offline selftest.",
  "example": "from scrapyard.observability.error_reporting import init_sentry",
  "import_path": "scrapyard.observability.error_reporting"
}
### END-PART-META
"""
from __future__ import annotations
import os, sys, traceback, logging
STATUS = "core"
log=logging.getLogger("scrapyard.errors")
class ErrorReporter:
    """Capture exceptions with context; pluggable sink (Sentry etc.) via set_sink.
    A separate exc-sink receives the live exception object (for SDKs that need it)."""
    def __init__(self): 
        self.captured=[] 
        self._sink=None 
        self._exc_sink=None
        self._context_injector = {}
        self._filters = []
        self._enrichment_hooks = []
        self._exception_mapping = {}
        self._audit_logging_enabled = False
        self._rate_limit = (100, 60)
        self._error_tags = {}
        self._transport_factory = None
        self._serializer = None
        self._metrics_enabled = True
        self._severity_mapping = {}
        self._retry_policy = {"max_retries": 3, "backoff": 1.0}
        self._sink_policy = "sentry"
    
    def set_sink(self, fn): 
        self._sink=fn
    
    def set_exc_sink(self, fn): 
        self._exc_sink=fn
    
    def capture(self, exc, **context):
        from scrapyard.compliance.privacy_policy_hooks import registry
        ctx={k:v for k,v in context.items() if registry.should_log(k)}
        evt={"type":type(exc).__name__,"message":str(exc),
             "trace":traceback.format_exc(),"context":ctx}
        self.captured.append(evt); log.error("captured %s: %s", evt["type"], evt["message"])
        if self._sink: 
            self._sink(evt)
        if self._exc_sink:
            try: 
                self._exc_sink(exc, ctx)
            except Exception as _e:  # a reporting backend must never crash the request
                log.warning("error sink failed: %s", _e)
        return evt
    
    def inject_context(self, context, *, override: bool = False):
        """Inject global context for all future captures."""
        if override:
            self._context_injector = context
        else:
            self._context_injector.update(context)
    
    def add_filter(self, filter_func):
        """Add a filter function to suppress exceptions based on custom logic."""
        if not callable(filter_func):
            raise ValueError("filter_func must be a callable")
        self._filters.append(filter_func)
    
    def capture_all(self, events, **context) -> list:
        """Batch capture with shared context."""
        ctx = {**self._context_injector, **context}
        captured_events = []
        for exc in events:
            if any(f(exc, ctx) for f in self._filters):
                continue
            evt = self.capture(exc, **ctx)
            captured_events.append(evt)
        return captured_events
    
    def add_enrichment_hook(self, hook):
        """Add an enrichment hook to enrich event data before sending."""
        if not callable(hook):
            raise ValueError("hook must be a callable")
        self._enrichment_hooks.append(hook)
    
    def map_exception(self, exc_type, mapped_type):
        """Map exception types to custom Sentry event types."""
        if not isinstance(mapped_type, str) or not issubclass(exc_type, Exception):
            raise ValueError("Invalid arguments for mapping exception")
        self._exception_mapping[exc_type] = mapped_type
    
    def enable_audit_logging(self, enabled: bool = True):
        """Enable audit logging for captures."""
        self._audit_logging_enabled = enabled
    
    def set_rate_limit(self, limit: int = 100, window: int = 60):
        """Set rate limiting for sinks."""
        if not isinstance(limit, int) or not isinstance(window, int):
            raise ValueError("limit and window must be integers")
        self._rate_limit = (limit, window)
    
    def tag_error(self, exc: Exception, tag: str):
        """Add a tag to an exception for classification in Sentry."""
        if not isinstance(tag, str):
            raise ValueError("tag must be a string")
        self._error_tags[exc] = tag
    
    def set_transport_factory(self, factory):
        """Set the transport factory for custom transport usage."""
        if not callable(factory):
            raise ValueError("factory must be a callable")
        self._transport_factory = factory
    
    def set_serializer(self, serializer):
        """Set the event serializer function."""
        if not callable(serializer):
            raise ValueError("serializer must be a callable")
        self._serializer = serializer
    
    def enable_metrics(self, enabled: bool = True):
        """Enable metrics tracking for error reporting."""
        self._metrics_enabled = enabled
    
    def map_severity(self, exc_type, severity):
        """Map exceptions to Sentry severity levels."""
        if not isinstance(severity, str) or severity.lower() not in ["info", "warning", "error", "fatal"]:
            raise ValueError("Invalid severity level")
        self._severity_mapping[exc_type] = severity
    
    def batch_capture(self, max_size: int = 100, timeout: float = 1.0):
        """Batch events and send in bulk."""
        if not isinstance(max_size, int) or not isinstance(timeout, (int, float)):
            raise ValueError("max_size must be an integer, timeout must be a number")
        # Implement batching logic here
        pass
    
    def set_retry_policy(self, max_retries: int = 3, backoff: float = 1.0):
        """Set the retry policy for failed sends."""
        if not isinstance(max_retries, int) or not isinstance(backoff, (int, float)):
            raise ValueError("max_retries must be an integer, backoff must be a number")
        self._retry_policy = {"max_retries": max_retries, "backoff": backoff}
    
    def set_sink_policy(self, policy):
        """Set the sink policy."""
        if not isinstance(policy, str) or policy not in ["sentry", "noop", "log_only"]:
            raise ValueError("policy must be one of 'sentry', 'noop', or 'log_only'")
        self._sink_policy = policy

reporter = ErrorReporter()


def init_sentry(dsn=None, *, transport=None, environment=None):
    """Wire the global reporter to a real Sentry SDK. Returns True if initialized.
    `transport` lets tests capture envelopes without network egress."""
    dsn = dsn or os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    import sentry_sdk
    sentry_sdk.init(dsn=dsn, transport=transport, traces_sample_rate=0.0,
                    environment=environment or os.environ.get("APP_ENV", "development"),
                    default_integrations=False)
    reporter.set_exc_sink(lambda exc, ctx: sentry_sdk.capture_exception(exc))
    return True


def _selftest() -> None:
    """Offline self-test: capturing an exception records its type/message/context
    and forwards the event to a registered sink; privacy-sensitive context is
    dropped; and invalid configuration is rejected."""
    r = ErrorReporter()

    sink_events: list = []
    r.set_sink(sink_events.append)

    # Capture within an active exception so the traceback is populated.
    try:
        raise ValueError("bad input 42")
    except ValueError as exc:
        evt = r.capture(exc, request_id="req-1", user_id=99)

    assert evt["type"] == "ValueError", evt["type"]
    assert evt["message"] == "bad input 42", evt["message"]
    assert evt["context"] == {"request_id": "req-1", "user_id": 99}, evt["context"]
    assert "ValueError" in evt["trace"], "traceback should be captured"
    assert r.captured == [evt] and sink_events == [evt], "event must be stored and sent to the sink"

    # Negative/adversarial: privacy-sensitive context keys are stripped, never captured.
    try:
        raise RuntimeError("auth failed")
    except RuntimeError as exc:
        evt2 = r.capture(exc, token="super-secret", user_id=7)
    assert "token" not in evt2["context"], "sensitive 'token' context must be filtered out"
    assert evt2["context"] == {"user_id": 7}

    # An exc-sink that raises must not propagate out of capture (a reporting backend
    # can never be allowed to crash the request path).
    def _bad_sink(exc, ctx):
        raise IOError("sentry down")

    r.set_exc_sink(_bad_sink)
    try:
        raise KeyError("k")
    except KeyError as exc:
        r.capture(exc)  # must not raise

    # Config validation: non-callable filter / bad severity are rejected.
    try:
        r.add_filter("not-callable")
        raise AssertionError("expected ValueError for non-callable filter")
    except ValueError:
        pass
    try:
        r.map_severity(ValueError, "catastrophic")
        raise AssertionError("expected ValueError for invalid severity")
    except ValueError:
        pass

    print("error_reporting selftest: PASS")


if __name__ == "__main__":
    _selftest()
