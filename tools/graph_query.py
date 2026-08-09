#!/usr/bin/env python3
"""
graph_query.py — dependency-graph intelligence over the capability graph.

Once the yard has hundreds of parts you stop being able to hold the edges in
your head. This answers the questions that matter for safe change:

    python tools/graph_query.py requires <cap>     # what <cap> needs (transitive)
    python tools/graph_query.py dependents <cap>   # what needs <cap> (transitive)
    python tools/graph_query.py impact <cap>        # what breaks if <cap> is removed
    python tools/graph_query.py safe-remove <cap>   # is it safe to remove? blockers if not
    python tools/graph_query.py why <from> <to>     # a dependency path from->to, if any
    python tools/graph_query.py orphans             # caps nothing depends on (leaf consumers)

Treats concrete and meta capabilities uniformly: an edge is an edge. Also
reports which shipped *patterns* pull a capability, since "removing X breaks
3 patterns" is the impact signal that actually matters.
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPS = os.path.join(ROOT, "capabilities", "capabilities.json")
PAT = os.path.join(ROOT, "patterns")


def load_graph() -> dict:
    with open(CAPS, encoding="utf-8") as f:
        return json.load(f)


def edges(graph: dict) -> dict[str, list[str]]:
    """Forward edges: cap -> [caps it requires], for concrete and meta alike."""
    e: dict[str, list[str]] = {}
    for c, info in graph["concrete"].items():
        e[c] = list(info.get("requires", []))
    for m, info in graph["meta"].items():
        e[m] = list(info["requires"])
    return e


def reverse(e: dict[str, list[str]]) -> dict[str, list[str]]:
    r: dict[str, list[str]] = {k: [] for k in e}
    for src, deps in e.items():
        for d in deps:
            r.setdefault(d, []).append(src)
    return r


def closure(start: str, adj: dict[str, list[str]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    stack = list(adj.get(start, []))
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        stack.extend(adj.get(n, []))
    return sorted(out)


def find_path(src: str, dst: str, adj: dict[str, list[str]]) -> list[str] | None:
    from collections import deque
    q = deque([[src]])
    seen = {src}
    while q:
        path = q.popleft()
        if path[-1] == dst:
            return path
        for nxt in adj.get(path[-1], []):
            if nxt not in seen:
                seen.add(nxt)
                q.append(path + [nxt])
    return None


def patterns_using(cap: str, graph: dict, e: dict) -> list[str]:
    """Which shipped patterns transitively pull this capability."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import resolve as R
    hits = []
    if not os.path.isdir(PAT):
        return hits
    for name in sorted(os.listdir(PAT)):
        spec = R.load_pattern(name)
        if not spec:
            continue
        res = R.resolve_capabilities(graph, list(spec.get("requires", [])))
        # a capability is "used" if it's a resolved part OR an expanded subsystem
        part_caps = {info["capability"] for info in res["parts"].values()}
        if cap in part_caps or cap in res["subsystems"]:
            hits.append(name)
    return hits


def kind(cap: str, graph: dict) -> str:
    if cap in graph["concrete"]:
        return "concrete:" + graph["concrete"][cap]["status"]
    if cap in graph["meta"]:
        return "meta"
    return "UNKNOWN"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    graph = load_graph()
    e = edges(graph)
    r = reverse(e)
    cmd = argv[0]

    if cmd == "orphans":
        orphans = sorted(c for c in graph["concrete"] if not r.get(c) and not any(c in v for v in e.values()))
        print(f"{len(orphans)} capabilities nothing depends on:")
        for c in orphans:
            print(f"  {c}  ({kind(c, graph)})")
        return 0

    if cmd == "why" and len(argv) >= 3:
        path = find_path(argv[1], argv[2], e)
        if path:
            print(" -> ".join(path))
        else:
            print(f"no dependency path: {argv[1]} -> {argv[2]}")
        return 0

    if len(argv) < 2:
        print("need a capability argument")
        return 2
    cap = argv[1]
    if kind(cap, graph) == "UNKNOWN":
        print(f"unknown capability: {cap}")
        return 1

    if cmd == "requires":
        deps = closure(cap, e)
        print(f"{cap} ({kind(cap, graph)}) requires {len(deps)} capabilities (transitive):")
        print("  direct:  " + (", ".join(e.get(cap, [])) or "none"))
        print("  all:     " + (", ".join(deps) or "none"))
        return 0

    if cmd in ("dependents", "impact", "safe-remove"):
        deps = closure(cap, r)
        direct = r.get(cap, [])
        pats = patterns_using(cap, graph, e)
        if cmd == "dependents":
            print(f"{len(deps)} capabilities depend on {cap} (transitive):")
            print("  direct:  " + (", ".join(sorted(direct)) or "none"))
            print("  all:     " + (", ".join(deps) or "none"))
        elif cmd == "impact":
            print(f"IMPACT of removing {cap} ({kind(cap, graph)}):")
            print(f"  breaks {len(deps)} capabilities: " + (", ".join(deps) or "none"))
            print(f"  affects {len(pats)} patterns: " + (", ".join(pats) or "none"))
        else:  # safe-remove
            if not deps and not pats:
                print(f"SAFE to remove {cap}: nothing depends on it.")
            else:
                print(f"NOT SAFE to remove {cap}:")
                if direct:
                    print("  directly required by: " + ", ".join(sorted(direct)))
                if pats:
                    print("  used by patterns:     " + ", ".join(pats))
        return 0

    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
