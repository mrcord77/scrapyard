#!/usr/bin/env python3
"""
check_compositions.py — validate every composition's bound capabilities exist.

A composition binds two or more capabilities and describes the glue between
them. If a bound capability isn't in the graph, the recipe is dead — catch it
here.

    python tools/check_compositions.py
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPS = os.path.join(ROOT, "capabilities", "capabilities.json")
COMP = os.path.join(ROOT, "compositions")


def load_compositions() -> list[dict]:
    out = []
    if not os.path.isdir(COMP):
        return out
    for name in sorted(os.listdir(COMP)):
        cj = os.path.join(COMP, name, "composition.json")
        if os.path.exists(cj):
            out.append(json.load(open(cj, encoding="utf-8")))
    return out


def main() -> int:
    graph = json.load(open(CAPS, encoding="utf-8"))
    known = set(graph["concrete"]) | set(graph["meta"])
    comps = load_compositions()
    errors = []
    for c in comps:
        for cap in c.get("binds", []):
            if cap not in known:
                errors.append(f"{c['name']}: binds unknown capability '{cap}'")
        if len(c.get("binds", [])) < 2:
            errors.append(f"{c['name']}: a composition must bind >=2 capabilities")
    if errors:
        print("COMPOSITION VALIDATION FAILED:")
        for e in errors:
            print("  - " + e)
        return 1
    print(f"compositions OK: {len(comps)} recipes, all bound capabilities resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
