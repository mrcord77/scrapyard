#!/usr/bin/env python3
"""
new_part.py — scaffold one new part with a valid metadata.

    python tools/new_part.py <layer> <name> "Short purpose." [dep1 dep2 ...]

Creates scrapyard/<layer>/<name>.py if absent, then re-index with
tools/index_catalog.py. For permanent parts, also add the entry to
tools/scaffold_parts.py so a fresh bootstrap reproduces it.
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "scrapyard")
OPEN_M = "### PART-META-JSON"
CLOSE_M = "### END-PART-META"


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    layer, name, purpose = argv[0], argv[1], argv[2]
    deps = argv[3:]
    ldir = os.path.join(PKG, layer)
    os.makedirs(ldir, exist_ok=True)
    init = os.path.join(ldir, "__init__.py")
    if not os.path.exists(init):
        with open(init, "w", encoding="utf-8") as f:
            f.write(f'"""{layer} layer parts."""\n')
    path = os.path.join(ldir, f"{name}.py")
    if os.path.exists(path):
        print(f"refusing to overwrite existing part: {path}")
        return 1
    ip = f"scrapyard.{layer}.{name}"
    m = {
        "name": name, "layer": layer, "purpose": purpose, "addition": True,
        "status": "skeleton", "dependencies": deps,
        "inputs": "See function signatures in this module.",
        "outputs": "See function/return annotations in this module.",
        "files_created": [], "security_notes": "Validate external input; never log secrets/PII.",
        "ai_usage": f"Import what you need from `{ip}`.",
        "example": f"from {ip} import *", "import_path": ip,
    }
    block = json.dumps(m, indent=2)
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            f'"""\n{name} — {purpose}\n\n{OPEN_M}\n{block}\n{CLOSE_M}\n"""\n'
            "from __future__ import annotations\n\nSTATUS = \"skeleton\"\n\n\n"
            "def _not_implemented(*_a, **_k):\n"
            f'    raise NotImplementedError("scrapyard part not yet implemented: {ip}")\n'
        )
    print(f"created {os.path.relpath(path, ROOT)} — now run: python tools/index_catalog.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
