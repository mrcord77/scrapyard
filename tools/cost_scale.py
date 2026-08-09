#!/usr/bin/env python3
"""
cost_scale.py — estimated operating cost across user tiers.

Static, order-of-magnitude cost projection for a plan's cost-bearing
capabilities at 10 / 100 / 1k / 100k active users. Every number is an ESTIMATE,
not a quote — it exists to surface operational surprises early.

    python tools/cost_scale.py <pattern> [--domain d] [--stage s] [--md <dir>]
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
MODEL = os.path.join(ROOT, "operations", "cost_model.json")
TIERS = [10, 100, 1_000, 100_000]


def model() -> dict:
    return json.load(open(MODEL, encoding="utf-8"))["capabilities"]


def project(part_names: set[str]):
    m = model()
    relevant = {n: m[n] for n in part_names if n in m}
    per_tier = {}
    for users in TIERS:
        total = 0.0
        for n, c in relevant.items():
            total += c["base"] + c["per_1k"] * (users / 1000.0)
        per_tier[users] = round(total, 2)
    return relevant, per_tier


def plan_parts(argv):
    import resolve as R
    plan = R.plan_from_args(argv)
    return plan["present"]



def render_md(relevant, per_tier) -> str:
    L = ["# Cost & scale projection (ESTIMATES)\n",
         "Order-of-magnitude monthly USD for planning only — not a quote.\n",
         "| Users | Est. monthly |", "|---|---|"]
    for u, c in per_tier.items():
        L.append(f"| {u:,} | ${c:,.0f} |")
    L.append("\n## Cost drivers")
    for n, c in sorted(relevant.items(), key=lambda kv: -kv[1]["per_1k"]):
        L.append(f"- **{n}** — base ${c['base']}/mo + ${c['per_1k']}/1k users — {c['note']}")
    return "\n".join(L)


def main(argv):
    if not argv:
        print(__doc__); return 2
    relevant, per_tier = project(plan_parts(argv))
    if "--md" in argv:
        open(os.path.join(argv[argv.index("--md") + 1], "COST.md"), "w", encoding="utf-8").write(render_md(relevant, per_tier))
        print(f"wrote COST.md ({len(relevant)} cost drivers)")
        return 0
    print("estimated monthly cost (USD, rough):")
    for u, c in per_tier.items():
        print(f"  {u:>7,} users  ~${c:,.0f}/mo")
    print("drivers:", ", ".join(sorted(relevant)) or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
