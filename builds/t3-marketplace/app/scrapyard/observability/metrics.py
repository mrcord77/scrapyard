"""
metrics — Prometheus-style counters/gauges/histograms (hand-rolled, no client lib).

### PART-META-JSON
{
  "name": "metrics",
  "layer": "observability",
  "purpose": "In-process metrics registry: thread-safe counters, gauges, and histogram observations with a snapshot API and a text exporter emitting valid Prometheus exposition format (HELP/TYPE lines, sanitized metric names, histogram _count/_sum series). Implemented by hand — the prometheus-client library is NOT used or required.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Metric names and numeric values from application code.",
  "outputs": "Snapshot dicts; Prometheus exposition-format text for a /metrics endpoint.",
  "files_created": [],
  "security_notes": "Metric names are sanitized to the Prometheus charset before export, so arbitrary strings cannot inject extra exposition lines. Do not put user identifiers or other PII into metric names — they are unbounded label-free series and end up in every scrape. The registry is per-process; counters reset on restart.",
  "ai_usage": "from scrapyard.observability.metrics import registry; registry.incr('requests_total'); expose registry.export_prometheus() at /metrics.",
  "example": "registry.incr('jobs_done_total'); registry.observe('job_seconds', 1.42); print(registry.export_prometheus())",
  "import_path": "scrapyard.observability.metrics"
}
### END-PART-META
"""
from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional, Union

STATUS = "core"

_NAME_OK = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_NAME_FIX = re.compile(r"[^a-zA-Z0-9_:]")


def _sanitize(name: str) -> str:
    """Coerce an arbitrary name into a valid Prometheus metric name."""
    name = _NAME_FIX.sub("_", str(name))
    if not name or not _NAME_OK.match(name):
        name = "_" + name
    return name


class Metrics:
    """In-process counters/gauges/histograms with a Prometheus-style text export."""

    def __init__(self):
        self._c: Dict[str, float] = {}
        self._g: Dict[str, float] = {}
        self._h: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def incr(self, name: str, by: Union[int, float] = 1) -> None:
        with self._lock:
            self._c[name] = self._c.get(name, 0) + by

    def gauge(self, name: str, value: Union[int, float]) -> None:
        with self._lock:
            self._g[name] = value

    def observe(self, name: str, value: Union[int, float]) -> None:
        with self._lock:
            self._h.setdefault(name, []).append(value)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._c),
                "gauges": dict(self._g),
                "histograms": {k: {"count": len(v), "sum": sum(v)} for k, v in self._h.items()},
            }

    def reset(self) -> None:
        with self._lock:
            self._c.clear(); self._g.clear(); self._h.clear()

    def export_prometheus(self) -> str:
        """Render all metrics in Prometheus text exposition format 0.0.4:
        HELP/TYPE headers, sanitized names, histograms as _count and _sum."""
        snap = self.snapshot()
        lines: List[str] = []
        for name, value in snap["counters"].items():
            metric = _sanitize(name)
            lines.append(f"# HELP {metric} Counter {name!r} (scrapyard metrics)")
            lines.append(f"# TYPE {metric} counter")
            lines.append(f"{metric} {float(value)}")
        for name, value in snap["gauges"].items():
            metric = _sanitize(name)
            lines.append(f"# HELP {metric} Gauge {name!r} (scrapyard metrics)")
            lines.append(f"# TYPE {metric} gauge")
            lines.append(f"{metric} {float(value)}")
        for name, agg in snap["histograms"].items():
            metric = _sanitize(name)
            lines.append(f"# HELP {metric} Summary of {name!r} observations (scrapyard metrics)")
            lines.append(f"# TYPE {metric} summary")
            lines.append(f"{metric}_count {float(agg['count'])}")
            lines.append(f"{metric}_sum {float(agg['sum'])}")
        return "\n".join(lines) + ("\n" if lines else "")


registry = Metrics()


def _selftest() -> None:
    m = Metrics()
    m.incr("requests_total")
    m.incr("requests_total", 2)
    m.gauge("queue_depth", 7)
    m.observe("latency_seconds", 0.5)
    m.observe("latency_seconds", 1.5)
    m.incr("weird name-with!chars")

    snap = m.snapshot()
    assert snap["counters"]["requests_total"] == 3
    assert snap["gauges"]["queue_depth"] == 7
    assert snap["histograms"]["latency_seconds"] == {"count": 2, "sum": 2.0}

    text = m.export_prometheus()
    # every non-comment line must be "<valid_name> <float>"
    sample_re = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]* -?\d+(\.\d+)?([eE][+-]?\d+)?$")
    samples = [ln for ln in text.strip().splitlines() if not ln.startswith("#")]
    assert samples, "no samples exported"
    for ln in samples:
        assert sample_re.match(ln), f"invalid exposition line: {ln!r}"
    # TYPE headers present and histograms export _count/_sum
    assert "# TYPE requests_total counter" in text
    assert "# TYPE queue_depth gauge" in text
    assert "latency_seconds_count 2.0" in text and "latency_seconds_sum 2.0" in text
    # invalid chars sanitized, no raw spaces/! in metric names
    assert "weird_name_with_chars 1.0" in text
    assert text.endswith("\n")

    # threaded increments stay consistent
    def worker():
        for _ in range(1000):
            m.incr("threaded_total")
    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert m.snapshot()["counters"]["threaded_total"] == 4000

    m.reset()
    assert m.export_prometheus() == ""

    # module-level registry works
    registry.incr("selftest_total")
    assert "selftest_total" in registry.export_prometheus()

    print("metrics selftest: PASS")


if __name__ == "__main__":
    _selftest()
