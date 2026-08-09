#!/usr/bin/env python3
"""
registry.py — the engineering knowledge registry.

One queryable surface over everything the yard knows: parts, capabilities,
patterns, domains, compositions, alternatives, lessons, operational profiles,
and confidence. Turns a pile of JSON files into searchable engineering memory.

    python tools/registry.py build                 # write registry.json
    python tools/registry.py solve <keyword>       # what solves this problem?
    python tools/registry.py depends <capability>  # what depends on this?
    python tools/registry.py about <capability>    # everything known about it
    python tools/registry.py stats                 # coverage across the registry
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _load(path, default=None):
    p = os.path.join(ROOT, path)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def build_index() -> dict:
    cat = _load("catalog.json", {"layers": {}})
    graph = _load("capabilities/capabilities.json", {"concrete": {}, "meta": {}})
    conf = _load("confidence/confidence.json", {"capabilities": {}})["capabilities"]
    ops = _load("operations/profiles.json", {"profiles": {}})["profiles"]

    caps = {}
    for name, c in graph.get("concrete", {}).items():
        caps[name] = {
            "kind": "concrete", "part": c["part"], "layer": c["layer"],
            "purpose": c.get("purpose", ""), "requires": c.get("requires", []),
            "status": c.get("status"),
            "confidence": conf.get(name, conf.get(name.split(".")[-1], {})).get("confidence_score"),
            "has_ops_profile": name in ops,
        }
    for name, m in graph.get("meta", {}).items():
        caps[name] = {"kind": "meta", "purpose": m.get("description", ""),
                      "requires": m["requires"], "has_ops_profile": name in ops}

    def names(d):
        return sorted(os.listdir(os.path.join(ROOT, d))) if os.path.isdir(os.path.join(ROOT, d)) else []

    alts = {f[:-5] for f in names("alternatives") if f.endswith(".json")}
    comps = []
    for n in names("compositions"):
        c = _load(f"compositions/{n}/composition.json")
        if c:
            comps.append({"name": c["name"], "binds": c["binds"]})
    lessons = []
    lf = "lessons/lessons.jsonl"
    if os.path.exists(os.path.join(ROOT, lf)):
        for line in open(os.path.join(ROOT, lf), encoding="utf-8"):
            if line.strip():
                lessons.append(json.loads(line))

    return {
        "schema": "scrapyard/registry@1",
        "capabilities": caps,
        "patterns": [p for p in names("patterns")],
        "domains": [d for d in names("domains")],
        "compositions": comps,
        "alternatives": sorted(alts),
        "lessons": lessons,
        "totals": {
            "capabilities": len(caps),
            "with_ops_profile": sum(1 for c in caps.values() if c.get("has_ops_profile")),
            "with_alternatives": len(alts),
            "patterns": len(names("patterns")), "domains": len(names("domains")),
            "compositions": len(comps), "lessons": len(lessons),
        },
    }


def load_registry() -> dict:
    p = os.path.join(ROOT, "registry.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else build_index()


def cmd_solve(kw: str) -> int:
    reg = load_registry()
    kw = kw.lower()
    hits = [(n, c) for n, c in reg["capabilities"].items()
            if kw in n.lower() or kw in c.get("purpose", "").lower()]
    print(f"{len(hits)} capabilities related to '{kw}':")
    for n, c in sorted(hits)[:20]:
        extra = f" [{c['status']}]" if c.get("status") else " [meta]"
        print(f"  {n}{extra} — {c.get('purpose','')[:70]}")
    return 0


def cmd_depends(cap: str) -> int:
    import graph_query as GQ
    graph = GQ.load_graph()
    e = GQ.edges(graph)
    r = GQ.reverse(e)
    deps = GQ.closure(cap, r)
    print(f"{len(deps)} capabilities depend on {cap}:")
    print("  " + (", ".join(deps) or "none"))
    return 0


def cmd_about(cap: str) -> int:
    reg = load_registry()
    c = reg["capabilities"].get(cap) or reg["capabilities"].get(cap)
    if not c:
        print(f"unknown capability: {cap}"); return 1
    print(f"# {cap} ({c['kind']})")
    print(f"  purpose: {c.get('purpose','')}")
    if c.get("part"):
        print(f"  part: {c['part']}  layer: {c['layer']}  status: {c.get('status')}  "
              f"confidence: {c.get('confidence')}")
    print(f"  requires: {', '.join(c.get('requires', [])) or 'none'}")
    print(f"  has operational profile: {c.get('has_ops_profile', False)}")
    if cap in reg["alternatives"]:
        print(f"  alternatives: yes (alternatives/{cap}.json)")
    comps = [x["name"] for x in reg["compositions"] if cap in x["binds"]]
    if comps:
        print(f"  compositions: {', '.join(comps)}")
    ls = [L["id"] + ":" + L["title"] for L in reg["lessons"]
          if cap in L["applies_to"].get("capabilities", [])]
    if ls:
        print(f"  lessons: {'; '.join(ls)}")
    return 0


def main(argv):
    if not argv:
        print(__doc__); return 2
    cmd = argv[0]
    if cmd == "build":
        reg = build_index()
        json.dump(reg, open(os.path.join(ROOT, "registry.json"), "w", encoding="utf-8"), indent=2)
        print("wrote registry.json:", reg["totals"])
        return 0
    if cmd == "stats":
        print(json.dumps(load_registry()["totals"], indent=2)); return 0
    if cmd == "solve" and len(argv) >= 2:
        return cmd_solve(argv[1])
    if cmd == "depends" and len(argv) >= 2:
        return cmd_depends(argv[1])
    if cmd == "about" and len(argv) >= 2:
        return cmd_about(argv[1])
    print(__doc__); return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
