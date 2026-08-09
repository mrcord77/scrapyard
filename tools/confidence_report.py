#!/usr/bin/env python3
"""
confidence_report.py — how trustworthy is what we're about to ship?

Reports the confidence distribution over a resolved plan (or the whole catalog),
and names the lowest-confidence parts so you know what rests on stubs.

    python tools/confidence_report.py <pattern> [--domain d] [--stage s]
    python tools/confidence_report.py --all
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
CONF = os.path.join(ROOT, "confidence", "confidence.json")


def load() -> dict:
    return json.load(open(CONF, encoding="utf-8"))["capabilities"]


def summarize(part_names):
    conf = load()
    def lookup(n):
        return conf.get(n) or conf.get(n.split(".")[-1]) or {"status": "unknown", "confidence_score": 0.0}
    rows = [(n, lookup(n)) for n in part_names]
    dist = {}
    for _, c in rows:
        dist[c["status"]] = dist.get(c["status"], 0) + 1
    scores = [c["confidence_score"] for _, c in rows]
    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    lowest = sorted(rows, key=lambda r: r[1]["confidence_score"])[:8]
    return {"distribution": dist, "avg": avg, "count": len(rows), "lowest": lowest}


def render_md(s) -> str:
    L = ["# Confidence report\n",
         f"Average confidence across {s['count']} parts: **{s['avg']}**\n",
         "Distribution: " + ", ".join(f"{k} {v}" for k, v in sorted(s["distribution"].items())) + "\n",
         "## Lowest-confidence parts (build these or treat as provisional)"]
    for n, c in s["lowest"]:
        L.append(f"- **{n}** — {c['status']} ({c['confidence_score']}): {c.get('confidence_reason','')}")
    return "\n".join(L)


def main(argv):
    if not argv:
        print(__doc__); return 2
    if argv[0] == "--all":
        names = list(load().keys())
    else:
        import resolve as R
        pat = R.load_pattern(argv[0])
        if not pat:
            print(f"unknown pattern: {argv[0]}"); return 1
        wanted = list(pat["requires"])
        if "--domain" in argv:
            d = R.load_domain(argv[argv.index("--domain") + 1])
            if d: wanted += d.get("capability_hints", [])
        if "--stage" in argv:
            st = R.load_stages(); wanted, _ = R.filter_by_stage(wanted, argv[argv.index("--stage")+1], st)
        res = R.resolve_capabilities(R.load_graph(), wanted)
        names = [i["capability"] for i in res["parts"].values()]
    s = summarize(names)
    print(f"avg confidence {s['avg']} over {s['count']} parts; "
          + ", ".join(f"{k}:{v}" for k, v in sorted(s["distribution"].items())))
    print("lowest:")
    for n, c in s["lowest"]:
        print(f"  {n:20} {c['status']:11} {c['confidence_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
