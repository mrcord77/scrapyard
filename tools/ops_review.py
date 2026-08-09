#!/usr/bin/env python3
"""
ops_review.py — what will this cost and how will it break in production?

Surfaces operational profiles for the operationally-significant parts in a plan:
cost, scaling limits, failure modes, monitoring/backup/recovery needs.

    python tools/ops_review.py <pattern> [--domain d] [--stage s] [--md <dir>]
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
OPS = os.path.join(ROOT, "operations", "profiles.json")


def profiles() -> dict:
    return json.load(open(OPS, encoding="utf-8"))["profiles"]


def review(part_names: set[str]) -> list[tuple]:
    p = profiles()
    return [(n, p[n]) for n in sorted(part_names) if n in p]


def render_md(items) -> str:
    L = ["# Operational review\n",
         "Operationally-significant parts in this build and what they demand in production.\n"]
    for n, pr in items:
        L.append(f"## {n}")
        L.append(f"- **Cost:** {pr['cost']}")
        L.append(f"- **Scaling limit:** {pr['scaling_limit']}")
        L.append(f"- **Failure modes:** {', '.join(pr['failure_modes'])}")
        L.append(f"- **Monitor:** {', '.join(pr['monitoring'])}")
        L.append(f"- **Backup:** {pr['backup']}  •  **Recovery:** {pr['recovery']}")
        L.append(f"- **Recommended stage:** {pr['recommended_stage']}  •  "
                 f"**Avoid when:** {pr['do_not_use_when']}\n")
    return "\n".join(L)


def plan_parts(argv):
    import resolve as R
    plan = R.plan_from_args(argv)
    return plan["present"]



def main(argv):
    if not argv:
        print(__doc__); return 2
    items = review(plan_parts(argv))
    if "--md" in argv:
        out = argv[argv.index("--md") + 1]
        open(os.path.join(out, "OPERATIONS.md"), "w", encoding="utf-8").write(render_md(items))
        print(f"wrote OPERATIONS.md ({len(items)} profiles)")
    else:
        print(f"{len(items)} operationally-significant parts:")
        for n, pr in items:
            print(f"  {n:18} cost={pr['cost'].split('(')[0].strip()}; "
                  f"stage={pr['recommended_stage']}; failures={len(pr['failure_modes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
