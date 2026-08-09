#!/usr/bin/env python3
"""
simulate_plan.py — static failure prediction for a plan.

Not load testing — architectural simulation. Inspects a resolved plan, lists
the failure scenarios whose triggering capabilities are present, and flags any
high-severity scenario whose safeguards are missing from the build.

    python tools/simulate_plan.py <pattern> [--domain d] [--stage s]
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
SIM = os.path.join(ROOT, "simulations", "scenarios.json")


def scenarios() -> list[dict]:
    return json.load(open(SIM, encoding="utf-8"))["scenarios"]


def analyze(part_names: set[str]):
    applicable = []
    for s in scenarios():
        if set(s["affected"]) & part_names:
            have = [x for x in s["safeguards"] if x in part_names]
            missing = [x for x in s["safeguards"] if x not in part_names]
            applicable.append({**s, "have": have, "missing": missing,
                               "mitigated": len(missing) == 0})
    return applicable


def plan_parts(argv):
    import resolve as R
    plan = R.plan_from_args(argv)
    return plan["present"]



def render_md(items) -> str:
    L = ["# Failure simulation\n",
         "Scenarios whose triggers are present in this build.\n"]
    for s in items:
        flag = "OK" if s["mitigated"] else "UNMITIGATED"
        L.append(f"## {s['id']} [{s['severity']}/{flag}] {s['trigger']}")
        L.append(f"- Expected failure: {s['expected']}")
        L.append(f"- Safeguards present: {', '.join(s['have']) or 'none'}")
        if s["missing"]:
            L.append(f"- **Missing safeguards: {', '.join(s['missing'])}**")
        L.append(f"- Detect via: {s['detection']}  •  Recover: {s['recovery']}\n")
    return "\n".join(L)


def main(argv):
    if not argv:
        print(__doc__); return 2
    parts = plan_parts(argv)
    items = analyze(parts)
    if "--md" in argv:
        open(os.path.join(argv[argv.index("--md") + 1], "SIMULATION.md"), "w", encoding="utf-8").write(render_md(items))
        unmit = sum(1 for s in items if not s["mitigated"] and s["severity"] == "high")
        print(f"wrote SIMULATION.md ({len(items)} scenarios, {unmit} high-severity unmitigated)")
        return 0
    print(f"{len(items)} applicable failure scenarios:")
    worst_unmitigated = False
    for s in items:
        flag = "mitigated" if s["mitigated"] else "UNMITIGATED"
        print(f"  {s['id']} [{s['severity']:6}] {flag:11} {s['trigger']}")
        if not s["mitigated"]:
            print(f"        missing: {', '.join(s['missing'])}")
            if s["severity"] == "high":
                worst_unmitigated = True
    if worst_unmitigated:
        print("  => high-severity scenario(s) without mitigation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
