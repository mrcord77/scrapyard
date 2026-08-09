#!/usr/bin/env python3
"""
tech_debt.py — what's weak, what's owed, and what to build next.

Surfaces the maintenance reality of the yard and turns it into an ordered
upgrade plan: the highest-leverage stubs to implement, low-confidence parts that
patterns lean on, and promoted lessons that haven't been turned into rules yet.

    python tools/tech_debt.py report      # the debt picture
    python tools/tech_debt.py upgrade     # prioritized next-build plan
"""
from __future__ import annotations
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _load(path, default=None):
    p = os.path.join(ROOT, path)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def stub_pattern_demand():
    """draft (stub) capabilities ranked by how many patterns pull them."""
    import resolve as R
    conf = _load("confidence/confidence.json", {"capabilities": {}})["capabilities"]
    graph = R.load_graph()
    counts = Counter()
    pat_dir = os.path.join(ROOT, "patterns")
    for name in sorted(os.listdir(pat_dir)):
        spec = R.load_pattern(name)
        if not spec:
            continue
        res = R.resolve_capabilities(graph, list(spec["requires"]))
        for info in res["parts"].values():
            cap = info["capability"]
            st = conf.get(cap, conf.get(cap.split(".")[-1], {})).get("status")
            if st == "draft":
                counts[cap] += 1
    return counts


def unapplied_promotions():
    p = os.path.join(ROOT, "lessons", "promotions.jsonl")
    out = []
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                if not r.get("applied"):
                    out.append(r)
    return out


def report() -> int:
    conf = _load("confidence/confidence.json", {"capabilities": {}})["capabilities"]
    status = Counter(c["status"] for c in conf.values())
    demand = stub_pattern_demand()
    promos = unapplied_promotions()
    print("TECHNICAL DEBT")
    print("  confidence mix: " + ", ".join(f"{k} {v}" for k, v in sorted(status.items())))
    print(f"  stub capabilities pulled by patterns: {len(demand)}")
    print(f"  unapplied lesson promotions: {len(promos)}")
    if promos:
        for r in promos:
            print(f"    {r['lesson_id']} -> {r['target']}: {r['reason']}")
    print("  top stub demand:")
    for cap, n in demand.most_common(8):
        print(f"    {cap:20} {n} patterns")
    return 0


def upgrade() -> int:
    demand = stub_pattern_demand()
    promos = unapplied_promotions()
    print("UPGRADE PLAN (highest leverage first)\n")
    print("1) Implement these stubs — each unblocks the most patterns:")
    for i, (cap, n) in enumerate(demand.most_common(6), 1):
        print(f"   {i}. {cap}  (pulled by {n} patterns)")
    print("\n2) Turn promoted lessons into rules:")
    if promos:
        for r in promos:
            print(f"   - {r['lesson_id']} -> {r['target']}: {r['reason']}")
    else:
        print("   - none pending")
    print("\n3) Suggested first full subsystem: authentication")
    print("   (auth_routes, session_manager, password_reset, email_verification, oauth_google, mfa_totp)")
    print("   Rationale: pulled by nearly every pattern; its compositions, alternatives,")
    print("   and lessons already exist, so implementing it activates the most reasoning.")
    return 0


def main(argv):
    if not argv:
        print(__doc__); return 2
    if argv[0] == "report":
        return report()
    if argv[0] == "upgrade":
        return upgrade()
    print(__doc__); return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
