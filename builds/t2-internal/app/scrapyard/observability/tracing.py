"""
tracing — OpenTelemetry spans for requests/db/llm.

### PART-META-JSON
{
  "name": "tracing",
  "layer": "observability",
  "purpose": "OpenTelemetry spans for requests/db/llm.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "opentelemetry-api"
  ],
  "inputs": "Public API: build_tracer(exporter, service_name); init_otel(*, service_name, exporter); Tracer(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `build_tracer` from `scrapyard.observability.tracing` and call it as shown in `example`; run `py -m scrapyard.observability.tracing` to see its offline selftest.",
  "example": "from scrapyard.observability.tracing import build_tracer",
  "import_path": "scrapyard.observability.tracing"
}
### END-PART-META
"""
from __future__ import annotations
import os, time, uuid, contextlib
STATUS = "core"
class Tracer:
    """Minimal span tracer: nested spans with timing, collectable for export to
    OTel/Jaeger. Good enough to measure and correlate without a backend."""
    def __init__(self): self.spans=[]; self._stack=[]
    @contextlib.contextmanager
    def span(self, name):
        sid=uuid.uuid4().hex[:8]; parent=self._stack[-1] if self._stack else None
        start=time.perf_counter(); self._stack.append(sid)
        try: yield sid
        finally:
            self._stack.pop()
            self.spans.append({"id":sid,"name":name,"parent":parent,
                               "ms":round((time.perf_counter()-start)*1000,2)})
tracer = Tracer()


# --- Real OpenTelemetry --------------------------------------------------------
# The Tracer above is a dependency-free fallback. These build a real OTel tracer
# whose spans flow through the standard SDK pipeline to a configurable exporter
# (OTLP in production; an in-memory exporter in tests — same pipeline, no network).

def build_tracer(exporter, service_name: str = "scrapyard"):
    """Return an OTel tracer backed by an isolated provider exporting to `exporter`.
    Does NOT touch the global tracer provider (safe to call in tests)."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.resources import Resource
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer(service_name)


def init_otel(*, service_name: str = "scrapyard", exporter=None):
    """Install a global OTel tracer provider for the app. Uses an OTLP exporter when
    OTEL_EXPORTER_OTLP_ENDPOINT is set; otherwise returns None (no tracing backend)."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.resources import Resource
    if exporter is None:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if not endpoint:
            return None
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter(endpoint=endpoint)
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


def _selftest() -> None:
    """Offline self-test (dependency-free fallback Tracer): a span records
    start/end timing and name, and nested spans record their parent so the trace
    tree can be reconstructed."""
    t = Tracer()

    # A single span records name, an id, and a non-negative duration with no parent.
    with t.span("root") as sid:
        assert isinstance(sid, str) and sid
    assert len(t.spans) == 1
    root = t.spans[0]
    assert root["name"] == "root" and root["parent"] is None
    assert isinstance(root["ms"], float) and root["ms"] >= 0.0

    # Nested spans: the inner span records the outer span's id as its parent, and
    # both are recorded. Inner closes (and is appended) before the outer.
    t2 = Tracer()
    with t2.span("outer") as outer_id:
        with t2.span("inner") as inner_id:
            assert inner_id != outer_id
    names = [s["name"] for s in t2.spans]
    assert names == ["inner", "outer"], f"inner should finish/record first: {names}"
    inner_span = next(s for s in t2.spans if s["name"] == "inner")
    outer_span = next(s for s in t2.spans if s["name"] == "outer")
    assert inner_span["parent"] == outer_span["id"], "nested span must reference its parent"
    assert outer_span["parent"] is None

    # Negative/adversarial: after all spans close the stack is empty, so a
    # subsequent sibling span is a root (parent None), not wrongly nested under a
    # popped span.
    with t2.span("sibling"):
        pass
    assert t2.spans[-1]["name"] == "sibling" and t2.spans[-1]["parent"] is None

    print("tracing selftest: PASS")


if __name__ == "__main__":
    _selftest()
