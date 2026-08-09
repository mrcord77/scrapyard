"""
eval_harness — Run prompt evals against fixtures.

### PART-META-JSON
{
  "name": "eval_harness",
  "layer": "ai",
  "purpose": "Run prompt evals against fixtures.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: EvalHarness(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `EvalHarness` from `scrapyard.ai.eval_harness` and call it as shown in `example`; run `py -m scrapyard.ai.eval_harness` to see its offline selftest.",
  "example": "from scrapyard.ai.eval_harness import EvalHarness",
  "import_path": "scrapyard.ai.eval_harness"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
class EvalHarness:
    """Run a callable over labeled cases and score with a custom matcher. The basis
    for prompt/model regression testing."""
    def __init__(self, fn, matcher=None):
        self.fn = fn
        self.matcher = matcher or (lambda out, expected: expected in out)
    def run(self, cases: list[dict]) -> dict:
        results = []
        for c in cases:
            out = self.fn(c["input"])
            results.append({"input": c["input"], "passed": bool(self.matcher(out, c["expected"]))})
        passed = sum(r["passed"] for r in results)
        return {"total": len(results), "passed": passed,
                "score": round(passed / len(results), 3) if results else 0.0, "results": results}


def _selftest():
    # default matcher: expected substring in output
    h = EvalHarness(lambda q: f"the answer is {q.upper()}")
    report = h.run([
        {"input": "alpha", "expected": "ALPHA"},
        {"input": "beta", "expected": "BETA"},
        {"input": "gamma", "expected": "nope"},
    ])
    assert report["total"] == 3 and report["passed"] == 2
    assert abs(report["score"] - 0.667) < 1e-9
    assert report["results"][2]["passed"] is False

    # custom matcher
    exact = EvalHarness(lambda x: x * 2, matcher=lambda out, exp: out == exp)
    r2 = exact.run([{"input": 3, "expected": 6}, {"input": 3, "expected": 7}])
    assert r2["passed"] == 1

    # empty case list
    assert EvalHarness(lambda x: x).run([]) == {"total": 0, "passed": 0,
                                               "score": 0.0, "results": []}
    print("eval_harness selftest passed")


if __name__ == "__main__":
    _selftest()
