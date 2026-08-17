"""
health — Liveness/readiness checks aggregating dependency probes.

### PART-META-JSON
{
  "name": "health",
  "layer": "foundation",
  "purpose": "Health probe registry: register sync/async dependency probes (with per-probe timeouts and error handlers), aggregate them into a readiness report with uptime and per-check status, serialize reports as JSON or Prometheus gauge lines, and expose a cheap liveness payload.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Named probe callables returning truthy/awaitable-truthy; optional timeout seconds and error handlers.",
  "outputs": "Report dicts {status, ok, uptime_s, checks}; JSON/Prometheus serializations.",
  "files_created": [],
  "security_notes": "Probe errors are reported as exception CLASS names only, so connection strings or credentials inside exception messages never leak through the health endpoint (custom error handlers can override this — keep them equally terse). A timed-out or failing probe degrades the report instead of crashing the endpoint, so health checks cannot be used to DoS the app via a slow dependency. Do not expose the readiness report unauthenticated if probe names reveal internal topology.",
  "ai_usage": "health.register('db', db_probe, timeout=2.0); return await health.report() from the readiness route.",
  "example": "health.register('db', lambda: check_db()); report = await health.report()",
  "import_path": "scrapyard.foundation.health"
}
### END-PART-META
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from typing import Awaitable, Callable, Dict, List, Optional, Tuple, Union

STATUS = "core"

logger = logging.getLogger("scrapyard.foundation.health")

Probe = Union[Callable[[], Awaitable[bool]], Callable[[], bool]]
AuditHook = Callable[[str, str, str], None]


class HealthProbeTimeoutError(Exception):
    pass

class InvalidProbeTypeError(Exception):
    pass

class DuplicateProbeError(Exception):
    pass

class MissingProbeError(Exception):
    pass

class InvalidReportFormatError(Exception):
    pass


class HealthRegistry:
    def __init__(self) -> None:
        self._probes: Dict[str, Tuple[Probe, Optional[float], Optional[Callable[[Exception], str]]]] = {}
        self._started = time.time()
        self._health_probe_timeout = 5.0
        self._liveness_timeout = 1.0

    def register(self, name: str, probe: Probe, timeout: Optional[float] = None,
                 error_handler: Optional[Callable[[Exception], str]] = None) -> None:
        if not callable(probe):
            raise InvalidProbeTypeError(f"Probe '{name}' is not callable")
        if name in self._probes:
            raise DuplicateProbeError(f"Probe '{name}' already registered")
        self._probes[name] = (probe, timeout, error_handler)

    def register_async(self, name: str, probe: Callable[[], Awaitable[bool]]) -> None:
        if not inspect.iscoroutinefunction(probe):
            raise InvalidProbeTypeError(f"Probe '{name}' is not an async callable")
        self.register(name, probe)

    def register_sync(self, name: str, probe: Callable[[], bool]) -> None:
        if inspect.iscoroutinefunction(probe):
            raise InvalidProbeTypeError(f"Probe '{name}' is async; use register_async")
        self.register(name, probe)

    def unregister(self, name: str) -> None:
        if name not in self._probes:
            raise MissingProbeError(f"Probe '{name}' not registered")
        del self._probes[name]

    def bulk_register(self, probes: List[Tuple[str, Probe, Dict]]) -> None:
        for name, probe, metadata in probes:
            self.register(name, probe,
                          timeout=metadata.get("timeout"),
                          error_handler=metadata.get("error_handler"))

    def on_probe_start(self, name: str, category: str) -> None:
        """Audit hook fired before each probe runs (override or rely on the log)."""
        logger.debug("probe_start name=%s category=%s", name, category)

    def on_probe_end(self, name: str, category: str, result: str) -> None:
        """Audit hook fired after each probe with its recorded result."""
        logger.debug("probe_end name=%s category=%s result=%s", name, category, result)

    async def report(self, format: str = "default") -> Dict:
        """Run every probe (sync or async, honouring timeouts) and aggregate.
        A slow or failing probe degrades the report; it never raises out."""
        checks: Dict[str, str] = {}
        ok = True
        for name, (probe, timeout, error_handler) in self._probes.items():
            self.on_probe_start(name, "readiness")
            effective_timeout = timeout if timeout is not None else self._health_probe_timeout
            try:
                res = probe()
                if inspect.isawaitable(res):
                    res = await asyncio.wait_for(res, effective_timeout)
                checks[name] = "ok" if res else "fail"
                ok = ok and bool(res)
            except (asyncio.TimeoutError, TimeoutError):
                checks[name] = "timeout"
                ok = False
            except Exception as e:
                if error_handler is not None:
                    checks[name] = error_handler(e)
                else:
                    # class name only: never leak DSNs/credentials via messages
                    checks[name] = f"error: {e.__class__.__name__}"
                ok = False
            self.on_probe_end(name, "readiness", checks[name])
        return {"status": "ok" if ok else "degraded",
                "ok": ok,
                "uptime_s": round(time.time() - self._started, 1),
                "checks": checks}

    def serialize_report(self, report: Dict, format: str = "json") -> str:
        if format == "json":
            return json.dumps(report)
        if format == "prometheus":
            lines = [
                "# HELP health_check_status Status of a health check (1 ok, 0 not ok)",
                "# TYPE health_check_status gauge",
            ]
            for name, status in report.get("checks", {}).items():
                value = 1 if status == "ok" else 0
                lines.append(f'health_check_status{{name="{name}"}} {value}')
            lines.append("# HELP health_overall_ok Overall health (1 ok, 0 degraded)")
            lines.append("# TYPE health_overall_ok gauge")
            lines.append(f"health_overall_ok {1 if report.get('ok') else 0}")
            return "\n".join(lines) + "\n"
        raise InvalidReportFormatError(f"Unsupported report format: {format}")


health = HealthRegistry()


def liveness(timeout: float = 1.0) -> Dict:
    """Cheap always-true liveness payload."""
    return {"status": "alive"}


def configure_health_probe_timeout(timeout: float):
    health._health_probe_timeout = timeout


def configure_liveness_timeout(timeout: float):
    health._liveness_timeout = timeout


def _selftest() -> None:
    async def main() -> None:
        reg = HealthRegistry()

        # sync + async probes, plus failure/error/timeout paths
        reg.register_sync("always_ok", lambda: True)
        reg.register_sync("fails", lambda: False)

        async def async_ok():
            return True
        reg.register_async("async_ok", async_ok)

        def blows_up():
            raise ConnectionError("postgres://user:SECRET@host/db unreachable")
        reg.register("errors", blows_up)

        async def sleepy():
            await asyncio.sleep(5)
            return True
        reg.register("slow", sleepy, timeout=0.05)

        reg.register("handled", blows_up, error_handler=lambda e: "custom-degraded")

        report = await reg.report()
        assert report["ok"] is False and report["status"] == "degraded"
        c = report["checks"]
        assert c["always_ok"] == "ok" and c["async_ok"] == "ok"
        assert c["fails"] == "fail" and c["slow"] == "timeout"
        assert c["errors"] == "error: ConnectionError"  # class only, no DSN leak
        assert "SECRET" not in json.dumps(report)
        assert c["handled"] == "custom-degraded"
        assert report["uptime_s"] >= 0

        # all-green report
        reg2 = HealthRegistry()
        reg2.register("db", lambda: True)
        good = await reg2.report()
        assert good["ok"] is True and good["status"] == "ok"

        # serialization: json round-trips; prometheus lines are well-formed
        assert json.loads(reg2.serialize_report(good, "json"))["ok"] is True
        prom = reg.serialize_report(report, "prometheus")
        assert 'health_check_status{name="always_ok"} 1' in prom
        assert 'health_check_status{name="fails"} 0' in prom
        assert "health_overall_ok 0" in prom
        try:
            reg.serialize_report(report, "yaml")
            raise AssertionError("bad format accepted")
        except InvalidReportFormatError:
            pass

        # registration guards
        try:
            reg.register("always_ok", lambda: True)
            raise AssertionError("duplicate accepted")
        except DuplicateProbeError:
            pass
        try:
            reg.register("nc", "not-callable")  # type: ignore[arg-type]
            raise AssertionError("non-callable accepted")
        except InvalidProbeTypeError:
            pass
        try:
            reg.register_async("sync_as_async", lambda: True)
            raise AssertionError("sync probe accepted as async")
        except InvalidProbeTypeError:
            pass
        try:
            reg.register_sync("async_as_sync", async_ok)
            raise AssertionError("async probe accepted as sync")
        except InvalidProbeTypeError:
            pass
        reg.unregister("slow")
        try:
            reg.unregister("slow")
            raise AssertionError("double unregister accepted")
        except MissingProbeError:
            pass

        # bulk registration with metadata
        reg3 = HealthRegistry()
        reg3.bulk_register([
            ("a", lambda: True, {}),
            ("b", lambda: True, {"timeout": 1.0}),
            ("c", blows_up, {"error_handler": lambda e: "meh"}),
        ])
        r3 = await reg3.report()
        assert r3["checks"] == {"a": "ok", "b": "ok", "c": "meh"}

        # module-level helpers
        assert liveness() == {"status": "alive"}
        configure_health_probe_timeout(2.5)
        assert health._health_probe_timeout == 2.5
        configure_liveness_timeout(0.5)
        assert health._liveness_timeout == 0.5

    asyncio.run(main())
    print("health selftest: PASS")


if __name__ == "__main__":
    _selftest()
