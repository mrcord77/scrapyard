#!/usr/bin/env python3
"""
maturity_dashboard.py — where is the yard real, and where is it still theory?

    python tools/maturity_dashboard.py            # console
    python tools/maturity_dashboard.py --md       # write MATURITY.md

Reports part counts by status/confidence and the "critical stubs": stub parts
that the shipped patterns depend on most, since those are the highest-leverage
things to implement next.
"""
from __future__ import annotations
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
CAT = os.path.join(ROOT, "catalog.json")
CONF = os.path.join(ROOT, "confidence", "confidence.json")
PAT = os.path.join(ROOT, "patterns")


def critical_stubs():
    """Stub parts ranked by how many patterns pull them."""
    import resolve as R
    conf = json.load(open(CONF, encoding="utf-8"))["capabilities"]
    graph = R.load_graph()
    counts = Counter()
    for name in sorted(os.listdir(PAT)):
        spec = R.load_pattern(name)
        if not spec:
            continue
        res = R.resolve_capabilities(graph, list(spec["requires"]))
        for info in res["parts"].values():
            cap = info["capability"]
            if conf.get(cap, {}).get("status") == "draft":
                counts[cap] += 1
    return counts.most_common(12)


def build():
    cat = json.load(open(CAT, encoding="utf-8"))
    conf = json.load(open(CONF, encoding="utf-8"))
    totals = cat["totals"] if "totals" in cat else {}
    status = Counter(c["status"] for c in conf["capabilities"].values())
    crit = critical_stubs()
    return totals, status, crit


def render(totals, status, crit) -> str:
    L = ["# Maturity dashboard\n",
         f"Parts: {totals.get('parts','?')} total — "
         f"{totals.get('core','?')} core, {totals.get('skeleton','?')} skeleton, "
         f"{totals.get('additions_beyond_source','?')} additions.\n",
         "Confidence: " + ", ".join(f"{k} {v}" for k, v in sorted(status.items())) + "\n",
         "## Critical stubs (most-depended-on unimplemented parts)",
         "Implementing these unblocks the most patterns:\n"]
    for cap, n in crit:
        L.append(f"- **{cap}** — pulled by {n} patterns")
    return "\n".join(L)


def main(argv):
    totals, status, crit = build()
    out = render(totals, status, crit)
    if "--md" in argv:
        open(os.path.join(ROOT, "MATURITY.md"), "w", encoding="utf-8").write(out)
        print("wrote MATURITY.md")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
