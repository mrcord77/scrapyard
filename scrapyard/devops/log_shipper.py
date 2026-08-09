"""
log_shipper — Real file-tail log shipping with filters, enrichers, rotation and
pluggable sinks.

### PART-META-JSON
{
  "name": "log_shipper",
  "layer": "devops",
  "purpose": "File-tail log shipper: reads new lines from a tracked byte offset, applies regex filters and enricher transforms, ships records to a Sink interface (in-memory, file, callable), and enforces a size-based rotation policy.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy"],
  "inputs": "Source log file path; sink instance; optional LogFilter/LogEnricher lists; LogRotationPolicy; LogShipperConfig ORM row for persisted config.",
  "outputs": "Shipped record dicts ({'line','source','offset', ...enrichments}) delivered to the sink; rotated .1 files; persisted offsets.",
  "files_created": ["<source>.offset (byte-offset checkpoint next to the tailed file, when persist_offset=True)", "<source>.1 (rotation artifact when the policy triggers)"],
  "security_notes": "Ships raw log lines: point it only at logs already scrubbed of secrets/PII, and treat sink destinations as sensitive config. No network I/O in this module itself - a sink decides where records go; the selftest uses the in-memory sink only. Enricher callables run in-process: register only trusted code (no eval of config strings).",
  "ai_usage": "shipper = setup_log_shipper(path, sink=InMemorySink(), filters=[LogFilter('errors', re.compile('ERROR'))]); call shipper.tick() on a schedule (or run_forever); sink.records holds shipped dicts.",
  "example": "from scrapyard.devops.log_shipper import setup_log_shipper, InMemorySink",
  "import_path": "scrapyard.devops.log_shipper"
}
### END-PART-META
"""
from __future__ import annotations

import abc
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from scrapyard.database.base_model import IntPKModel
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

logger = logging.getLogger(__name__)

STATUS = "core"
T = TypeVar('T')


class LogRotationPolicy:
    """Rotate the source file when it exceeds size_threshold bytes (time_threshold
    kept for API compatibility; size is the enforced trigger)."""

    def __init__(self, size_threshold: int, time_threshold: Optional[timedelta] = None):
        if size_threshold < 1:
            raise ValueError("size_threshold must be >= 1 byte")
        self.size_threshold = size_threshold
        self.time_threshold = time_threshold

    def should_rotate(self, path: str) -> bool:
        try:
            return os.path.getsize(path) >= self.size_threshold
        except OSError:
            return False


@dataclass
class LogFilter:
    """Only lines matching pattern are shipped."""
    name: str
    pattern: re.Pattern


@dataclass
class LogEnricher:
    """transform(record_dict) -> record_dict, applied to every shipped record."""
    name: str
    transform: Callable[[Dict[str, Any]], Dict[str, Any]]


class LogShipperConfig(IntPKModel):
    __tablename__ = 'log_shipper_configs'

    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        return cls(config=data)

    def to_dict(self) -> Dict[str, Any]:
        return self.config


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------

class Sink(abc.ABC):
    """Destination interface for shipped records."""

    @abc.abstractmethod
    def ship(self, record: Dict[str, Any]) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def flush(self) -> None:
        pass


class InMemorySink(Sink):
    """Collects records in memory (selftest / debugging)."""

    def __init__(self):
        self.records: List[Dict[str, Any]] = []

    def ship(self, record: Dict[str, Any]) -> None:
        self.records.append(record)


class FileSink(Sink):
    """Appends each record as a JSON line to a destination file."""

    def __init__(self, path: str):
        self.path = path

    def ship(self, record: Dict[str, Any]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")


class CallableSink(Sink):
    """Adapts any callable(record) into a sink (e.g. an HTTP poster you supply)."""

    def __init__(self, fn: Callable[[Dict[str, Any]], None]):
        if not callable(fn):
            raise TypeError("CallableSink requires a callable")
        self._fn = fn

    def ship(self, record: Dict[str, Any]) -> None:
        self._fn(record)


# ---------------------------------------------------------------------------
# The shipper: read-from-offset tail loop
# ---------------------------------------------------------------------------

class LogShipper:
    """Tails a log file from a persisted byte offset and ships new lines.

    Each tick(): read from last offset -> split complete lines -> filter ->
    enrich -> sink.ship(record) -> checkpoint offset -> apply rotation policy.
    Truncation (offset > file size) is detected and resets the offset to 0.
    """

    def __init__(self, source: str, sink: Sink,
                 filters: Optional[List[LogFilter]] = None,
                 enrichers: Optional[List[LogEnricher]] = None,
                 rotation_policy: Optional[LogRotationPolicy] = None,
                 persist_offset: bool = True):
        if not isinstance(sink, Sink):
            raise TypeError("sink must implement the Sink interface")
        self.source = source
        self.sink = sink
        self.filters = filters or []
        self.enrichers = enrichers or []
        self.rotation_policy = rotation_policy
        self.persist_offset = persist_offset
        self._offset_path = source + ".offset"
        self.offset = self._load_offset()
        self.shipped_count = 0
        self.dropped_count = 0

    # -- offset checkpointing ------------------------------------------------
    def _load_offset(self) -> int:
        if self.persist_offset and os.path.exists(self._offset_path):
            try:
                with open(self._offset_path, "r", encoding="utf-8") as f:
                    return int(f.read().strip() or 0)
            except (OSError, ValueError):
                return 0
        return 0

    def _save_offset(self) -> None:
        if self.persist_offset:
            with open(self._offset_path, "w", encoding="utf-8") as f:
                f.write(str(self.offset))

    # -- pipeline ------------------------------------------------------------
    def _passes_filters(self, line: str) -> bool:
        return all(f.pattern.search(line) for f in self.filters)

    def _enrich(self, record: Dict[str, Any]) -> Dict[str, Any]:
        for e in self.enrichers:
            record = e.transform(record)
        return record

    def tick(self) -> int:
        """Ship all new complete lines since the last offset. Returns lines shipped."""
        if not os.path.exists(self.source):
            return 0
        size = os.path.getsize(self.source)
        if size < self.offset:  # truncated/rotated externally
            logger.info("source truncated; resetting offset (%d -> 0)", self.offset)
            self.offset = 0
        shipped = 0
        with open(self.source, "rb") as f:
            f.seek(self.offset)
            chunk = f.read()
        if chunk:
            # only complete lines; the trailing partial stays for the next tick
            last_nl = chunk.rfind(b"\n")
            if last_nl == -1:
                return 0
            complete = chunk[:last_nl + 1]
            self.offset += len(complete)
            for raw in complete.decode("utf-8", errors="replace").splitlines():
                if not raw.strip():
                    continue
                if not self._passes_filters(raw):
                    self.dropped_count += 1
                    continue
                record = self._enrich({"line": raw, "source": self.source,
                                       "offset": self.offset})
                self.sink.ship(record)
                self.shipped_count += 1
                shipped += 1
            self._save_offset()
        self._maybe_rotate()
        return shipped

    def _maybe_rotate(self) -> None:
        if self.rotation_policy and self.rotation_policy.should_rotate(self.source):
            rotated = self.source + ".1"
            try:
                if os.path.exists(rotated):
                    os.remove(rotated)
                os.replace(self.source, rotated)
                self.offset = 0
                self._save_offset()
                logger.info("rotated %s -> %s", self.source, rotated)
            except OSError as e:
                logger.error("rotation failed: %s", e)

    def run_forever(self, interval: float = 1.0,
                    max_ticks: Optional[int] = None) -> int:
        """Poll loop. max_ticks bounds it for tests; None runs until interrupted."""
        ticks = 0
        total = 0
        while max_ticks is None or ticks < max_ticks:
            total += self.tick()
            ticks += 1
            if max_ticks is None or ticks < max_ticks:
                time.sleep(interval)
        return total


def setup_log_shipper(source: str, sink: Optional[Sink] = None,
                      filters: Optional[List[LogFilter]] = None,
                      enrichers: Optional[List[LogEnricher]] = None,
                      rotation_policy: Optional[LogRotationPolicy] = None,
                      persist_offset: bool = True) -> LogShipper:
    """Build a ready-to-tick LogShipper (real setup, not a placeholder)."""
    return LogShipper(source=source, sink=sink or InMemorySink(),
                      filters=filters, enrichers=enrichers,
                      rotation_policy=rotation_policy,
                      persist_offset=persist_offset)


def shipper_from_config(config: Dict[str, Any], sink: Sink,
                        enrichers: Optional[List[LogEnricher]] = None) -> LogShipper:
    """Build from a persisted LogShipperConfig.config dict.

    Supported keys: source (required), filters: [{name, pattern}], rotation_policy:
    {size_threshold}. Enricher callables must be passed in code (never eval'd
    from config strings).
    """
    source = config.get("source")
    if not source:
        raise ValueError("config requires 'source'")
    filters = [LogFilter(f["name"], re.compile(f["pattern"]))
               for f in config.get("filters", [])]
    rp_cfg = config.get("rotation_policy")
    policy = LogRotationPolicy(int(rp_cfg["size_threshold"])) if rp_cfg else None
    return LogShipper(source, sink, filters=filters, enrichers=enrichers,
                      rotation_policy=policy)


def _selftest() -> bool:
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        src = os.path.join(td, "app.log")
        sink = InMemorySink()
        shipper = setup_log_shipper(
            src, sink,
            filters=[LogFilter("errors", re.compile(r"ERROR|WARN"))],
            enrichers=[LogEnricher("svc", lambda r: {**r, "service": "api"})],
        )

        # nothing yet
        assert shipper.tick() == 0

        with open(src, "a", encoding="utf-8") as f:
            f.write("INFO boot ok\nERROR db timeout\nWARN slow query\n")
        assert shipper.tick() == 2                      # INFO filtered out
        assert [r["line"] for r in sink.records] == ["ERROR db timeout", "WARN slow query"]
        assert all(r["service"] == "api" for r in sink.records)  # enriched
        assert shipper.dropped_count == 1

        # read-from-offset: appending ships ONLY the new line
        with open(src, "a", encoding="utf-8") as f:
            f.write("ERROR again\n")
        assert shipper.tick() == 1 and len(sink.records) == 3

        # partial line without newline is held back until completed
        with open(src, "a", encoding="utf-8") as f:
            f.write("ERROR half")
        assert shipper.tick() == 0
        with open(src, "a", encoding="utf-8") as f:
            f.write(" now done\n")
        assert shipper.tick() == 1
        assert sink.records[-1]["line"] == "ERROR half now done"

        # offset persists across shipper instances (checkpoint file)
        shipper2 = setup_log_shipper(src, sink, filters=[LogFilter("e", re.compile("ERROR"))])
        assert shipper2.offset == shipper.offset
        assert shipper2.tick() == 0                     # nothing new -> nothing reshipped

        # rotation: small threshold forces a rotate; offset resets
        pol_shipper = setup_log_shipper(src, InMemorySink(),
                                        rotation_policy=LogRotationPolicy(size_threshold=10))
        pol_shipper.tick()
        assert os.path.exists(src + ".1") and not os.path.exists(src)
        assert pol_shipper.offset == 0

        # truncation detection
        with open(src, "w", encoding="utf-8") as f:
            f.write("ERROR fresh\n")
        s3 = setup_log_shipper(src, sink2 := InMemorySink(), persist_offset=False)
        s3.offset = 10_000  # simulate stale large offset
        assert s3.tick() == 1 and sink2.records[0]["line"] == "ERROR fresh"

        # sinks: file sink writes JSONL; callable sink adapts a function
        out = os.path.join(td, "shipped.jsonl")
        fs = FileSink(out)
        fs.ship({"line": "x"})
        with open(out, encoding="utf-8") as f:
            assert json.loads(f.readline())["line"] == "x"
        got = []
        CallableSink(got.append).ship({"line": "y"})
        assert got == [{"line": "y"}]
        try:
            LogShipper(src, sink="not-a-sink")  # type: ignore[arg-type]
            raise AssertionError("bad sink accepted")
        except TypeError:
            pass

        # config-driven construction
        cfg = {"source": src, "filters": [{"name": "e", "pattern": "ERROR"}],
               "rotation_policy": {"size_threshold": 1024}}
        s4 = shipper_from_config(cfg, InMemorySink())
        assert s4.rotation_policy.size_threshold == 1024 and len(s4.filters) == 1

        # ORM config model roundtrip (no DB needed)
        m = LogShipperConfig.from_dict(cfg)
        assert m.to_dict() == cfg

    print("log_shipper selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
