"""polish_metadata: regenerate boilerplate PART-META-JSON fields from the code.

Replaces the generic "See function signatures" / "Review before production..." /
"read this metadata, wire the example" boilerplate with fields DERIVED from each
part's actual public API and imports, so every field is truthful and specific.
Only boilerplate fields are touched; already-real fields are preserved.

Usage:
  py tools/polish_metadata.py --check     # report how many parts still carry boilerplate
  py tools/polish_metadata.py --apply     # rewrite files (validates each still parses)
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SY = ROOT / "scrapyard"

BLOCK = re.compile(r"(### PART-META-JSON\n)(.*?)(\n### END-PART-META)", re.DOTALL)

BOILER = {
    "inputs": "See function signatures in this module.",
    "outputs": "See function/return annotations in this module.",
    "ai_usage_frag": "read this metadata, wire the example, install dependencies",
    "example_frag": "import *  # see module for concrete symbols",
    "secnote": "Review before production. Validate all external input; never log secrets/PII.",
}


def _sig(fn: ast.AST) -> str:
    a = fn.args
    names = [ar.arg for ar in a.posonlyargs + a.args]
    if a.vararg:
        names.append("*" + a.vararg.arg)
    if a.kwonlyargs:
        if not a.vararg:
            names.append("*")
        names += [k.arg for k in a.kwonlyargs]
    if a.kwarg:
        names.append("**" + a.kwarg.arg)
    return f"{fn.name}({', '.join(names)})"


def _ann(node) -> str | None:
    try:
        return ast.unparse(node) if node is not None else None
    except Exception:
        return None


def analyze(tree: ast.Module):
    pub_fns, pub_classes, imports = [], [], set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for al in n.names:
                imports.add(al.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module:
            imports.add(n.module.split(".")[0])
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_"):
            if n.name != "demo":
                pub_fns.append(n)
        elif isinstance(n, ast.ClassDef) and not n.name.startswith("_"):
            pub_classes.append(n)
    return pub_fns, pub_classes, imports


def gen_inputs(fns, classes) -> str:
    parts = [_sig(f) for f in fns[:5]]
    parts += [f"{c.name}(...)" for c in classes[:3]]
    if not parts:
        return "No public callables (module-level data/constants)."
    more = "" if len(fns) + len(classes) <= len(parts) else " (plus more)"
    return "Public API: " + "; ".join(parts) + more + "."


def gen_outputs(fns) -> str:
    anns = [(f.name, _ann(f.returns)) for f in fns if f.returns is not None]
    if anns:
        shown = "; ".join(f"{n} -> {a}" for n, a in anns[:5])
        return "Returns: " + shown + "."
    return "Return values of the public functions above (see their signatures)."


def gen_example(layer: str, name: str, fns, classes) -> str:
    sym = fns[0].name if fns else (classes[0].name if classes else None)
    base = f"scrapyard.{layer}.{name}"
    if sym:
        return f"from {base} import {sym}"
    return f"import {base}"


def gen_ai_usage(layer: str, name: str, fns, classes) -> str:
    sym = fns[0].name if fns else (classes[0].name if classes else None)
    if sym:
        return (f"Import `{sym}` from `scrapyard.{layer}.{name}` and call it as shown "
                f"in `example`; run `py -m scrapyard.{layer}.{name}` to see its offline selftest.")
    return f"Import from `scrapyard.{layer}.{name}`; see the module's public data/constants."


def gen_secnote(imports: set, src: str) -> str:
    bits = []
    if "html" in imports and "html.escape" in src:
        bits.append("Renders HTML with all caller text escaped via html.escape (XSS-safe); "
                    "any HTML 'slot' arguments are inserted verbatim and must be pre-escaped by the caller.")
    if {"sqlalchemy"} & imports or "IntPKModel" in src:
        bits.append("Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); "
                    "the composing app owns access control.")
    if {"requests", "httpx", "urllib", "socket", "http"} & imports:
        bits.append("Makes outbound network calls; set timeouts, validate URLs/hosts, and never send "
                    "secrets to untrusted endpoints.")
    if {"subprocess"} & imports or "os.system" in src:
        bits.append("Invokes subprocesses; never pass unsanitized input as command arguments.")
    if {"secrets", "hmac", "hashlib", "cryptography", "jwt"} & imports:
        bits.append("Handles cryptographic material; keep keys and tokens out of logs and source, "
                    "and prefer the vetted primitives it wraps.")
    if {"pathlib", "shutil"} & imports or re.search(r"\bopen\(", src):
        bits.append("Touches the local filesystem; validate paths to prevent traversal outside the intended root.")
    if not bits:
        bits.append("Pure computation: no network, filesystem, subprocess, secrets, or persistence; "
                    "validate ranges/values at the call site as usual.")
    return " ".join(bits)


def clean_purpose(p: str) -> str:
    # strip leading markdown bold / "The `x` module" cruft and truncation
    p = re.sub(r"^\**\s*", "", p).strip()
    p = re.sub(r"^The\s+`[^`]+`\s+module\s+", "", p)
    if p and not p[0].isupper():
        p = p[0].upper() + p[1:]
    if p and p[-1] not in ".!?":
        p += "."
    return p


def process(path: Path, apply: bool):
    src = path.read_text(encoding="utf-8")
    m = BLOCK.search(src)
    if not m:
        return None
    try:
        meta = json.loads(m.group(2))
    except json.JSONDecodeError:
        return ("bad-json", path)
    tree = ast.parse(src)
    fns, classes, imports = analyze(tree)
    layer, name = meta.get("layer", path.parent.name), meta.get("name", path.stem)
    changed = []

    def sval(k):  # field value as string, "" if absent or non-string
        v = meta.get(k)
        return v if isinstance(v, str) else ""

    if sval("inputs").strip() == BOILER["inputs"]:
        meta["inputs"] = gen_inputs(fns, classes); changed.append("inputs")
    if sval("outputs").strip() == BOILER["outputs"]:
        meta["outputs"] = gen_outputs(fns); changed.append("outputs")
    if BOILER["ai_usage_frag"] in sval("ai_usage"):
        meta["ai_usage"] = gen_ai_usage(layer, name, fns, classes); changed.append("ai_usage")
    if BOILER["example_frag"] in sval("example"):
        meta["example"] = gen_example(layer, name, fns, classes); changed.append("example")
    if sval("security_notes").strip() == BOILER["secnote"]:
        meta["security_notes"] = gen_secnote(imports, src); changed.append("security_notes")
    if sval("purpose").lstrip().startswith("**"):
        meta["purpose"] = clean_purpose(meta["purpose"]); changed.append("purpose")

    if not changed:
        return ("clean", path)
    if apply:
        new_json = json.dumps(meta, indent=2, ensure_ascii=False)
        new_src = src[:m.start(2)] + new_json + src[m.end(2):]
        try:
            ast.parse(new_src)  # never write a file that won't parse
        except SyntaxError as e:
            return ("parse-fail", path, str(e))
        path.write_text(new_src, encoding="utf-8")
    return ("changed", path, changed)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    counts = {"changed": 0, "clean": 0, "bad-json": 0, "parse-fail": 0}
    field_hits = {}
    for p in sorted(SY.rglob("*.py")):
        if p.name == "__init__.py":
            continue
        r = process(p, a.apply)
        if r is None:
            continue
        counts[r[0]] = counts.get(r[0], 0) + 1
        if r[0] == "changed":
            for f in r[2]:
                field_hits[f] = field_hits.get(f, 0) + 1
        if r[0] in ("bad-json", "parse-fail"):
            print(f"  !! {r[0]}: {p}")
    print(json.dumps({"mode": "apply" if a.apply else "check",
                      "counts": counts, "fields": field_hits}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
