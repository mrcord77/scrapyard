"""
scheduled_workflows — Multi-step scheduled workflow runner.

### PART-META-JSON
{
  "name": "scheduled_workflows",
  "layer": "jobs",
  "purpose": "Multi-step scheduled workflow runner.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: Workflow(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `Workflow` from `scrapyard.jobs.scheduled_workflows` and call it as shown in `example`; run `py -m scrapyard.jobs.scheduled_workflows` to see its offline selftest.",
  "example": "from scrapyard.jobs.scheduled_workflows import Workflow",
  "import_path": "scrapyard.jobs.scheduled_workflows"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

class Workflow:
    """A linear sequence of named steps with shared context. Stops at the first
    failing step and reports where it stopped (basis for durable workflows)."""
    def __init__(self, name: str):
        self.name = name; self.steps = []
    def step(self, name: str, fn):
        self.steps.append((name, fn)); return self
    def run(self, context: dict | None = None) -> dict:
        ctx = dict(context or {}); completed = []
        for name, fn in self.steps:
            try:
                fn(ctx)
            except Exception as e:
                return {"ok": False, "completed": completed, "failed_at": name, "error": str(e)}
            completed.append(name)
        return {"ok": True, "completed": completed}


def _selftest() -> None:
    """Offline self-test: ordered steps + shared context + fail-stop semantics."""
    # happy path: steps run in order and share the context dict
    wf = (Workflow("provision")
          .step("a", lambda ctx: ctx.__setitem__("a", 1))
          .step("b", lambda ctx: ctx.__setitem__("b", ctx["a"] + 1)))
    out = wf.run({"seed": 0})
    assert out == {"ok": True, "completed": ["a", "b"]}, "all steps must complete"

    # negative: a failing step stops the run and reports where it failed
    def boom(ctx):
        raise RuntimeError("kaboom")

    ran = []
    wf2 = (Workflow("risky")
           .step("first", lambda ctx: ran.append("first"))
           .step("second", boom)
           .step("third", lambda ctx: ran.append("third")))
    res = wf2.run()
    assert res["ok"] is False, "a failing step must fail the workflow"
    assert res["failed_at"] == "second", "must report the failing step"
    assert res["completed"] == ["first"], "steps after the failure must not run"
    assert "third" not in ran, "downstream step must be skipped after failure"
    assert "kaboom" in res["error"]
    print("scheduled_workflows self-test passed")


if __name__ == "__main__":
    _selftest()
