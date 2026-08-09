#!/usr/bin/env python3
"""
index_assets.py — catalog the non-code reusable assets.

Prompts, migrations, email templates, legal templates, OpenAPI specs, deploy
metadata, CI workflows — first-class assets so the AI stops regenerating them.
Walks assets/<kind>/* and records kind, purpose (first comment/heading line),
and any {{template_vars}}.

    python tools/index_assets.py
Output: assets/index.json
"""
from __future__ import annotations
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def first_purpose(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # strip common comment/heading markers
        s = re.sub(r"^(#+|--|//|<!--)\s*", "", s)
        s = re.sub(r"\s*-->$", "", s)
        return s
    return ""


def main() -> int:
    if not os.path.isdir(ASSETS):
        print("no assets/ dir")
        return 1
    items = []
    for kind in sorted(os.listdir(ASSETS)):
        kdir = os.path.join(ASSETS, kind)
        if not os.path.isdir(kdir):
            continue
        for fn in sorted(os.listdir(kdir)):
            path = os.path.join(kdir, fn)
            if not os.path.isfile(path):
                continue
            text = open(path, encoding="utf-8").read()
            vars_ = sorted(set(VAR_RE.findall(text)))
            items.append({
                "kind": kind,
                "name": fn,
                "path": os.path.relpath(path, ROOT),
                "purpose": first_purpose(text),
                "template_vars": vars_,
            })
    by_kind: dict[str, int] = {}
    for it in items:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
    payload = {
        "schema": "scrapyard/assets@1",
        "totals": {"assets": len(items), "kinds": len(by_kind), "by_kind": by_kind},
        "assets": items,
    }
    with open(os.path.join(ASSETS, "index.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"indexed {len(items)} assets across {len(by_kind)} kinds: "
          + ", ".join(f"{k}({v})" for k, v in sorted(by_kind.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
