#!/usr/bin/env python3
"""
index_catalog.py — build a VERIFIED catalog from part files.

Unlike the old version (which trusted each metadata's own "status" string and
silently dropped files without metadata), this tool verifies every
scrapyard/<layer>/*.py part file:

  a) parse the PART-META-JSON metadata — files missing one are reported with a
     loud stderr warning and still appear in the catalog flagged "undocumented";
  b) AST-scan for explicit placeholders (`raise NotImplementedError`, `pass`,
     or `...`) OUTSIDE legitimate abstract-base methods and self-test fixtures
     — these are "hollow markers";
  c) attempt importlib.import_module in-process;
  d) COMPUTE status: "core" only if metadata present + import OK + no hollow
     markers; otherwise "skeleton" with machine-readable reasons[].

The metadata's own "status" string is recorded as `metadata_status` but never
trusted. Output: catalog.json with per-part verified fields (metadata_ok,
imports_ok, hollow_markers, reasons) and aggregate totals.

    python tools/index_catalog.py            # write catalog.json
    python tools/index_catalog.py --out DIR  # verification run: write outputs to
                                             # DIR, leave the repo files untouched

No third-party dependencies (parts themselves may import theirs during the
import check; a missing dependency shows up honestly as imports_ok=false).
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "scrapyard")
OPEN_M = "### PART-META-JSON"
CLOSE_M = "### END-PART-META"
_INTERFACE_NAME_HINTS = ("interface", "abstract", "base", "protocol")


# ---------------------------------------------------------------- metadata ---

def extract_metadata(path: str, text: str) -> tuple[dict | None, str | None]:
    """Return (metadata, error). metadata is None when absent/broken."""
    if OPEN_M not in text or CLOSE_M not in text:
        return None, "no PART-META-JSON block"
    raw = text.split(OPEN_M, 1)[1].split(CLOSE_M, 1)[0].strip()
    try:
        m = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"bad metadata JSON: {e}"
    if not isinstance(m, dict):
        return None, "metadata JSON is not an object"
    return m, None


# ------------------------------------------------------------- hollow scan ---

def _is_nie_raise(node: ast.Raise) -> bool:
    exc = node.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    if isinstance(exc, ast.Name):
        return exc.id == "NotImplementedError"
    if isinstance(exc, ast.Attribute):
        return exc.attr == "NotImplementedError"
    return False


def _class_is_abcish(cls: ast.ClassDef) -> bool:
    for kw in cls.keywords:
        if kw.arg == "metaclass":
            v = kw.value
            name = v.id if isinstance(v, ast.Name) else (
                v.attr if isinstance(v, ast.Attribute) else "")
            if name == "ABCMeta":
                return True
    for b in cls.bases:
        name = b.id if isinstance(b, ast.Name) else (
            b.attr if isinstance(b, ast.Attribute) else "")
        if name in ("ABC", "ABCMeta", "Protocol"):
            return True
    return False


def _has_abstract_decorator(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for d in fn.decorator_list:
        node = d.func if isinstance(d, ast.Call) else d
        name = node.id if isinstance(node, ast.Name) else (
            node.attr if isinstance(node, ast.Attribute) else "")
        if name in ("abstractmethod", "abstractproperty"):
            return True
    return False


def _placeholder_statement(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ast.stmt | None:
    """Return a pass/ellipsis placeholder after ignoring a function docstring."""
    body = list(fn.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    if len(body) != 1:
        return None
    statement = body[0]
    if isinstance(statement, ast.Pass):
        return statement
    if (isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is Ellipsis):
        return statement
    return None


def _placeholder_is_abstract(
    cls: ast.ClassDef | None,
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    subclassed: set[str],
) -> bool:
    if _has_abstract_decorator(fn):
        return True
    if cls is None:
        return False
    return (_class_is_abcish(cls)
            or (any(h in cls.name.lower() for h in _INTERFACE_NAME_HINTS)
                and cls.name in subclassed))


def find_hollow_markers(tree: ast.Module) -> list[dict]:
    """Return NotImplementedError raises that are NOT legit ABC placeholders.

    Legit ABC placeholder = raise inside a method whose enclosing class uses
    ABCMeta/ABC/Protocol, or the method carries @abstractmethod, or the class
    name suggests an interface AND the class is subclassed in this module.
    """
    subclassed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for b in node.bases:
                if isinstance(b, ast.Name):
                    subclassed.add(b.id)
                elif isinstance(b, ast.Attribute):
                    subclassed.add(b.attr)

    hollow: list[dict] = []

    def visit(node: ast.AST, cls: ast.ClassDef | None,
              fn: ast.FunctionDef | ast.AsyncFunctionDef | None,
              in_selftest: bool = False) -> None:
        if isinstance(node, ast.ClassDef):
            for child in ast.iter_child_nodes(node):
                visit(child, node, None, in_selftest)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            selftest_context = in_selftest or node.name == "_selftest"
            placeholder = _placeholder_statement(node)
            if (placeholder is not None and not selftest_context
                    and not _placeholder_is_abstract(cls, node, subclassed)):
                where = ".".join(p for p in (
                    (cls.name if cls else ""), node.name) if p)
                kind = "pass" if isinstance(placeholder, ast.Pass) else "ellipsis"
                hollow.append({
                    "line": placeholder.lineno,
                    "in": where,
                    "kind": kind,
                })
            for child in ast.iter_child_nodes(node):
                visit(child, cls, node, selftest_context)
            return
        if isinstance(node, ast.Raise) and _is_nie_raise(node):
            legit = False
            if fn is not None and _has_abstract_decorator(fn):
                legit = True
            elif cls is not None and fn is not None:
                if _class_is_abcish(cls):
                    legit = True
                elif (any(h in cls.name.lower() for h in _INTERFACE_NAME_HINTS)
                      and cls.name in subclassed):
                    legit = True
            if not legit:
                where = ".".join(p for p in ((cls.name if cls else ""),
                                             (fn.name if fn else "<module>")) if p)
                hollow.append({
                    "line": node.lineno,
                    "in": where,
                    "kind": "NotImplementedError",
                })
            return
        for child in ast.iter_child_nodes(node):
            visit(child, cls, fn, in_selftest)

    for top in tree.body:
        visit(top, None, None)
    return hollow


# ------------------------------------------------------------ import check ---

def try_import(import_path: str) -> tuple[bool, str | None]:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        importlib.import_module(import_path)
        return True, None
    except BaseException as e:  # noqa: BLE001 — a part may raise anything at import
        return False, f"{type(e).__name__}: {e}"[:300]


# ----------------------------------------------------------------- collect ---

def verify_part(path: str, layer: str) -> dict:
    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
    stem = os.path.splitext(os.path.basename(path))[0]
    default_ip = f"scrapyard.{layer}.{stem}"
    with open(path, encoding="utf-8") as f:
        text = f.read()

    metadata, m_err = extract_metadata(path, text)
    metadata_ok = metadata is not None
    if not metadata_ok:
        print(f"WARNING: {rel}: {m_err} — part appears in catalog flagged "
              f"'undocumented'", file=sys.stderr)

    hollow: list[dict] = []
    parse_err: str | None = None
    try:
        tree = ast.parse(text)
        hollow = find_hollow_markers(tree)
    except SyntaxError as e:
        parse_err = f"SyntaxError: {e}"

    ip = (metadata or {}).get("import_path", default_ip)
    imports_ok, import_err = try_import(ip)

    reasons: list[str] = []
    if not metadata_ok:
        reasons.append(f"undocumented: {m_err}")
    if parse_err:
        reasons.append(parse_err)
    if hollow:
        reasons.append(
            "hollow placeholders at "
            + ", ".join(
                f"line {h['line']} ({h['in']}: {h['kind']})"
                for h in hollow[:5]
            )
            + ("…" if len(hollow) > 5 else ""))
    if not imports_ok:
        reasons.append(f"import failed: {import_err}")

    status = "core" if (metadata_ok and imports_ok and not hollow
                        and not parse_err) else "skeleton"

    return {
        "name": (metadata or {}).get("name", stem),
        "layer": (metadata or {}).get("layer", layer),
        "purpose": (metadata or {}).get("purpose", ""),
        "status": status,
        "reasons": reasons,
        "metadata_ok": metadata_ok,
        "metadata_status": (metadata or {}).get("status"),
        "imports_ok": imports_ok,
        "import_error": import_err,
        "hollow_markers": hollow,
        "addition": (metadata or {}).get("addition", False),
        "import_path": ip,
        "dependencies": (metadata or {}).get("dependencies", []),
        "file": rel,
    }


def collect() -> list[dict]:
    parts: list[dict] = []
    for layer in sorted(os.listdir(PKG)):
        ldir = os.path.join(PKG, layer)
        if not os.path.isdir(ldir) or layer == "__pycache__":
            continue
        for fn in sorted(os.listdir(ldir)):
            if fn.endswith(".py") and fn != "__init__.py":
                parts.append(verify_part(os.path.join(ldir, fn), layer))
    return parts


# ------------------------------------------------------------------- build ---

def build_catalog(parts: list[dict]) -> dict:
    layers: dict[str, list[dict]] = {}
    deps: set[str] = set()
    core = skeleton = additions = undocumented = import_failures = hollow_ct = 0
    for p in parts:
        layers.setdefault(p["layer"], []).append(p)
        for d in p.get("dependencies", []):
            deps.add(d)
        if p["status"] == "core":
            core += 1
        else:
            skeleton += 1
        if not p["metadata_ok"]:
            undocumented += 1
        if not p["imports_ok"]:
            import_failures += 1
        if p["hollow_markers"]:
            hollow_ct += 1
        if p.get("addition"):
            additions += 1
    return {
        "schema": "scrapyard/catalog@2",
        "note": ("status is COMPUTED by tools/index_catalog.py "
                 "(metadata_ok + imports_ok + no hollow markers), never taken "
                 "from the metadata's own status string"),
        "totals": {
            "layers": len(layers),
            "parts": len(parts),
            "core": core,
            "skeleton": skeleton,
            "undocumented": undocumented,
            "import_failures": import_failures,
            "hollow": hollow_ct,
            "additions_beyond_source": additions,
        },
        "aggregated_dependencies": sorted(deps),
        "layers": {
            layer: sorted(items, key=lambda x: x["name"])
            for layer, items in sorted(layers.items())
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None,
                    help="write catalog.json into this directory instead of "
                         "the repo root (verification run)")
    args = ap.parse_args(argv)

    parts = collect()
    cat = build_catalog(parts)

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        cat_path = os.path.join(args.out, "catalog.json")
    else:
        cat_path = os.path.join(ROOT, "catalog.json")

    with open(cat_path, "w", encoding="utf-8") as f:
        json.dump(cat, f, indent=2)

    t = cat["totals"]
    print(f"catalog written -> {cat_path}: {t['parts']} parts / {t['layers']} layers "
          f"({t['core']} verified core, {t['skeleton']} skeleton; "
          f"{t['undocumented']} undocumented, {t['import_failures']} import failures, "
          f"{t['hollow']} hollow)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
