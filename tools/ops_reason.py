#!/usr/bin/env python3
"""
ops_reason.py — the operational intelligence engine.

Operational profiles describe; this *reasons*. Given a dependency failure, it
traces what breaks downstream through the runtime dependency graph and reports
the cascade, the recovery paths, and the monitoring you'd need to see it coming.

    python tools/ops_reason.py failure <capability>     # what happens if X fails?
    python tools/ops_reason.py report <pattern> [--domain d] [--stage s]
    python tools/ops_reason.py deps <capability>         # runtime dependents of X
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
DEPS = os.path.join(ROOT, "operations", "dependency_models.json")
FAIL = os.path.join(ROOT, "operations", "failure_models.json")


def deps_model():
    return json.load(open(DEPS, encoding="utf-8"))


def fail_model():
    return json.load(open(FAIL, encoding="utf-8"))["failure_modes"]


def reverse_runtime():
    """capability -> [capabilities that runtime-depend on it]."""
    fwd = deps_model()["runtime_depends_on"]
    rev = {}
    for src, deps in fwd.items():
        for d in deps:
            rev.setdefault(d, []).append(src)
    return rev


def cascade(cap):
    """Transitive set of capabilities that break if `cap` fails."""
    rev = reverse_runtime()
    seen, stack, order = set(), list(rev.get(cap, [])), []
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n); order.append(n)
        stack.extend(rev.get(n, []))
    return order


def cmd_failure(cap):
    fm = fail_model()
    print(f"WHAT HAPPENS IF {cap} FAILS?\n")
    modes = fm.get(cap, [])
    if modes:
        print("Direct failure modes:")
        for m in modes:
            print(f"  - [{m['severity']}] {m['mode']}")
            print(f"      detect: {m['detect']}")
            print(f"      recover: {m['recovery']}")
    else:
        print("  (no failure model recorded for this capability directly)")
    casc = cascade(cap)
    print(f"\nDownstream impact — {len(casc)} capabilities break or degrade:")
    print("  " + (" -> ".join([cap] + casc) if casc else "nothing runtime-depends on it"))
    # recovery summary across the chain
    if casc:
        print("\nRecovery priority: restore", cap, "first; then verify",
              ", ".join(casc[:5]) + ("..." if len(casc) > 5 else ""))
    return 0


def cmd_deps(cap):
    rev = reverse_runtime()
    print(f"runtime dependents of {cap}: " + (", ".join(rev.get(cap, [])) or "none"))
    fwd = deps_model()["runtime_depends_on"]
    print(f"{cap} runtime-depends on: " + (", ".join(fwd.get(cap, [])) or "nothing"))
    return 0


def cmd_report(argv):
    import resolve as R
    plan = R.plan_from_args(argv)
    if not plan:
        print(f"unknown pattern: {argv[0]}"); return 1
    present = plan["present"]
    ext = set(deps_model()["external"])
    fm = fail_model()
    # external dependencies this plan relies on at runtime
    fwd = deps_model()["runtime_depends_on"]
    relied = set()
    for cap in present:
        for d in fwd.get(cap, []):
            if d in ext:
                relied.add(d)
    print(f"OPERATIONAL REASONING — {plan['pattern_name']}"
          + (f"+{plan['domain_name']}" if plan["domain_name"] else ""))
    print(f"\nExternal dependencies in play: {', '.join(sorted(relied)) or 'none'}")
    print("\nFailure reasoning (each external dep that this build leans on):")
    for dep in sorted(relied):
        casc = [c for c in cascade(dep) if c in present]
        modes = fm.get(dep, [])
        sev = max((m["severity"] for m in modes), default="?")
        print(f"  {dep} [{sev}] -> breaks in-plan: {', '.join(casc) or 'isolated'}")
        if modes:
            print(f"      recover: {modes[0]['recovery']}")
    # maintenance burden heuristic
    burden = len(relied) + sum(1 for c in present if c in fm)
    print(f"\nEstimated operational burden: {burden} moving parts needing monitoring/runbooks")
    return 0


def main(argv):
    if not argv:
        print(__doc__); return 2
    if argv[0] == "failure" and len(argv) >= 2:
        return cmd_failure(argv[1])
    if argv[0] == "deps" and len(argv) >= 2:
        return cmd_deps(argv[1])
    if argv[0] == "report" and len(argv) >= 2:
        return cmd_report(argv[1:])
    print(__doc__); return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
