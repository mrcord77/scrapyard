#!/usr/bin/env python3
"""
alternatives.py — evaluate competing implementations of a capability.

Selecting a part is only half the job; often there are several ways to satisfy
a capability with different tradeoffs. This scores them on simplicity /
scalability / security and recommends one, weighted by lifecycle stage (an MVP
weights simplicity; an enterprise build weights scale + security).

    python tools/alternatives.py list                       # capabilities with alternatives
    python tools/alternatives.py show <capability>          # the options + scores
    python tools/alternatives.py recommend <capability> [--stage mvp|growth|scale|enterprise]
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALT = os.path.join(ROOT, "alternatives")

# stage -> (w_simplicity, w_scalability, w_security)
WEIGHTS = {
    "mvp":        (3, 1, 2),
    "growth":     (2, 2, 2),
    "scale":      (1, 3, 2),
    "enterprise": (1, 2, 3),
}


def load(cap: str) -> dict | None:
    p = os.path.join(ALT, cap + ".json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def all_caps() -> list[str]:
    if not os.path.isdir(ALT):
        return []
    return sorted(f[:-5] for f in os.listdir(ALT) if f.endswith(".json"))


def score(opt: dict, stage: str) -> float:
    ws, wsc, wse = WEIGHTS.get(stage, WEIGHTS["growth"])
    total_w = ws + wsc + wse
    return round((opt["simplicity"] * ws + opt["scalability"] * wsc
                  + opt["security"] * wse) / total_w, 2)


def show(cap: str) -> int:
    spec = load(cap)
    if not spec:
        print(f"no alternatives for: {cap}")
        return 1
    print(f"{cap} — {spec['role']}")
    print(f"  {'option':28} {'simp':>4} {'scal':>4} {'sec':>4}  part")
    for o in spec["options"]:
        print(f"  {o['label']:28} {o['simplicity']:>4} {o['scalability']:>4} "
              f"{o['security']:>4}  {o['part_hint'] or '(external)'}")
        print(f"      {o['notes']}")
    return 0


def recommend(cap: str, stage: str) -> int:
    spec = load(cap)
    if not spec:
        print(f"no alternatives for: {cap}")
        return 1
    ranked = sorted(spec["options"], key=lambda o: score(o, stage), reverse=True)
    print(f"{cap} @ {stage} — recommendation")
    for i, o in enumerate(ranked):
        mark = "->" if i == 0 else "  "
        print(f"  {mark} {o['label']:28} score {score(o, stage)}  "
              f"({o['part_hint'] or 'external'})")
    best = ranked[0]
    print(f"\n  pick: {best['label']} — {best['notes']}")
    return 0


def explain(cap: str, stage: str) -> int:
    spec = load(cap)
    if not spec:
        print(f"no alternatives for: {cap}")
        return 1
    # pull lesson titles + part confidence to back the scores with evidence
    lessons = {}
    lf = os.path.join(ROOT, "lessons", "lessons.jsonl")
    if os.path.exists(lf):
        for line in open(lf, encoding="utf-8"):
            if line.strip():
                L = json.loads(line)
                lessons[L["id"]] = L["title"]
    conf = {}
    cf = os.path.join(ROOT, "confidence", "confidence.json")
    if os.path.exists(cf):
        conf = json.load(open(cf, encoding="utf-8"))["capabilities"]
    ranked = sorted(spec["options"], key=lambda o: score(o, stage), reverse=True)
    print(f"{cap} @ {stage} — explained")
    for i, o in enumerate(ranked):
        mark = "->" if i == 0 else "  "
        ph = o.get("part_hint")
        cstr = ""
        if ph and ph in conf:
            cstr = f" [part {conf[ph]['status']} {conf[ph]['confidence_score']}]"
        print(f"\n{mark} {o['label']}  score {score(o, stage)}{cstr}")
        for dim in ("simplicity", "scalability", "security"):
            why = o.get("reasons", {}).get(dim, "")
            print(f"     {dim:11} {o[dim]}  — {why}")
        if o.get("recommended_stages"):
            print(f"     best at: {', '.join(o['recommended_stages'])}")
        if o.get("contraindications"):
            print(f"     avoid when: {', '.join(o['contraindications'])}")
        for lid in o.get("lessons", []):
            print(f"     lesson {lid}: {lessons.get(lid, '(unknown)')}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "list":
        caps = all_caps()
        print(f"{len(caps)} capabilities have scored alternatives:")
        for c in caps:
            spec = load(c)
            print(f"  {c:18} {len(spec['options'])} options — {spec['role']}")
        return 0
    if cmd == "show" and len(argv) >= 2:
        return show(argv[1])
    if cmd == "recommend" and len(argv) >= 2:
        stage = argv[argv.index("--stage") + 1] if "--stage" in argv else "growth"
        return recommend(argv[1], stage)
    if cmd == "explain" and len(argv) >= 2:
        stage = argv[argv.index("--stage") + 1] if "--stage" in argv else "growth"
        return explain(argv[1], stage)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
