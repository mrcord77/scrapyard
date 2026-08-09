"""
cron_jobs — Declarative scheduled job registry.

### PART-META-JSON
{
  "name": "cron_jobs",
  "layer": "jobs",
  "purpose": "Declarative scheduled job registry.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: CronRegistry(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `CronRegistry` from `scrapyard.jobs.cron_jobs` and call it as shown in `example`; run `py -m scrapyard.jobs.cron_jobs` to see its offline selftest.",
  "example": "from scrapyard.jobs.cron_jobs import CronRegistry",
  "import_path": "scrapyard.jobs.cron_jobs"
}
### END-PART-META
"""
from __future__ import annotations
from datetime import datetime
STATUS = "core"

class CronRegistry:
    """Register named periodic jobs with a simple interval (seconds). due() returns
    jobs whose interval has elapsed; a real scheduler ticks this. Cron-expression
    parsing can layer on top, but interval covers the common case."""
    def __init__(self):
        self._jobs = {}  # name -> {fn, interval, last}
    def register(self, name: str, fn, interval_seconds: int):
        self._jobs[name] = {"fn": fn, "interval": interval_seconds, "last": None}
    def due(self, now: float) -> list[str]:
        out = []
        for name, j in self._jobs.items():
            if j["last"] is None or (now - j["last"]) >= j["interval"]:
                out.append(name)
        return out
    def run_due(self, now: float) -> list[str]:
        ran = []
        for name in self.due(now):
            self._jobs[name]["fn"](); self._jobs[name]["last"] = now; ran.append(name)
        return ran


def _selftest() -> None:
    """Offline self-test: interval due-computation with an injected clock."""
    calls = []
    reg = CronRegistry()
    reg.register("beat", lambda: calls.append("x"), interval_seconds=60)

    # a never-run job is due immediately (last is None)
    assert reg.due(now=1000.0) == ["beat"], "unrun job must be due"

    # run_due fires the fn and records the run time
    assert reg.run_due(now=1000.0) == ["beat"]
    assert calls == ["x"], "run_due must invoke the job function exactly once"

    # negative: not yet elapsed (30s < 60s interval) -> not due, not run
    assert reg.due(now=1030.0) == [], "job must not be due before its interval"
    assert reg.run_due(now=1030.0) == [] and calls == ["x"], "must not re-run early"

    # once the interval has elapsed it becomes due again
    assert reg.due(now=1060.0) == ["beat"], "job must be due once interval elapses"
    assert reg.run_due(now=1060.0) == ["beat"] and calls == ["x", "x"]
    print("cron_jobs self-test passed")


if __name__ == "__main__":
    _selftest()
