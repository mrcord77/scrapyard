"""
metadata_harvester — Parse every part's PART-META-JSON header + AST public API
into a sqlite catalog; incremental re-harvest by file hash.

### PART-META-JSON
{
  "name": "metadata_harvester",
  "layer": "curation",
  "purpose": "Harvest every part's PART-META-JSON header and AST public API (functions/classes/signatures) into a sqlite catalog, incrementally by file hash.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "db_path (sqlite file), root_dir (the scrapyard package directory).",
  "outputs": "sqlite catalog tables (parts); dict/list query results.",
  "files_created": ["<db_path> sqlite database"],
  "security_notes": "Read-only over source files; no network; parses with ast (never executes part code).",
  "ai_usage": "harvest(db_path, root) once, refresh(db_path, root) to update; get_part_info/list_all_parts/parts_in_layer to query. This is the curator's memory: feed its output to hybrid_searcher and metadata_composer.",
  "example": "from scrapyard.curation.metadata_harvester import harvest, get_part_info; harvest('catalog.db', 'scrapyard'); info = get_part_info('catalog.db', 'users')",
  "import_path": "scrapyard.curation.metadata_harvester"
}
### END-PART-META
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

STATUS = "core"

log = logging.getLogger("scrapyard.curation.metadata_harvester")

_META_RE = re.compile(r"###\s*PART-META-JSON\s*(\{.*?\})\s*###\s*END-PART-META",
                      re.DOTALL)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS parts (
    name TEXT NOT NULL,
    layer TEXT NOT NULL,
    purpose TEXT DEFAULT '',
    meta_json TEXT DEFAULT '{}',
    api_json TEXT DEFAULT '{}',
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    PRIMARY KEY (layer, name)
);
CREATE INDEX IF NOT EXISTS ix_parts_layer ON parts(layer);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    return conn


def _sig(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    a = fn.args
    parts: List[str] = []
    pos = a.posonlyargs + a.args
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    for arg, d in zip(pos, defaults):
        s = arg.arg
        if arg.annotation is not None:
            s += f": {ast.unparse(arg.annotation)}"
        if d is not None:
            s += "=..."
        parts.append(s)
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    for arg, d in zip(a.kwonlyargs, a.kw_defaults):
        s = arg.arg
        if arg.annotation is not None:
            s += f": {ast.unparse(arg.annotation)}"
        if d is not None:
            s += "=..."
        parts.append(s)
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    ret = f" -> {ast.unparse(fn.returns)}" if fn.returns is not None else ""
    pre = "async " if isinstance(fn, ast.AsyncFunctionDef) else ""
    return f"{pre}{fn.name}({', '.join(parts)}){ret}"


def parse_part(path: Path) -> Optional[Dict[str, Any]]:
    """Extract PART-META-JSON + public API from one part file. None if the
    file has no meta header (e.g. __init__.py) or does not parse."""
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    m = _META_RE.search(src)
    meta: Dict[str, Any] = {}
    if m:
        try:
            meta = json.loads(m.group(1))
        except json.JSONDecodeError:
            log.warning("bad PART-META-JSON in %s", path)
    api: Dict[str, Any] = {"functions": [], "classes": [], "constants": []}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                api["functions"].append(_sig(node))
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            methods = [_sig(x) for x in node.body
                       if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and (not x.name.startswith("_") or x.name == "__init__")]
            api["classes"].append({
                "name": node.name,
                "bases": [ast.unparse(b) for b in node.bases],
                "methods": methods,
            })
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    api["constants"].append(t.id)
    if not meta and not (api["functions"] or api["classes"]):
        return None
    return {
        "name": meta.get("name", path.stem),
        "layer": meta.get("layer", path.parent.name),
        "purpose": meta.get("purpose", ""),
        "meta": meta,
        "api": api,
    }


def _iter_part_files(root_dir: str):
    for p in sorted(Path(root_dir).rglob("*.py")):
        if p.name == "__init__.py" or "__pycache__" in p.parts:
            continue
        yield p


def _hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def harvest(db_path: str, root_dir: str, force: bool = False) -> int:
    """Full sweep. Skips files whose hash is unchanged unless force=True.
    Returns the number of parts inserted or updated."""
    conn = _connect(db_path)
    try:
        known = {row[0]: row[1] for row in conn.execute(
            "SELECT file_path, file_hash FROM parts")}
        changed = 0
        for p in _iter_part_files(root_dir):
            fp = str(p)
            h = _hash(p)
            if not force and known.get(fp) == h:
                continue
            info = parse_part(p)
            if info is None:
                continue
            conn.execute(
                "INSERT INTO parts (name, layer, purpose, meta_json, api_json,"
                " file_path, file_hash) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(layer, name) DO UPDATE SET purpose=excluded.purpose,"
                " meta_json=excluded.meta_json, api_json=excluded.api_json,"
                " file_path=excluded.file_path, file_hash=excluded.file_hash",
                (info["name"], info["layer"], info["purpose"],
                 json.dumps(info["meta"]), json.dumps(info["api"]), fp, h))
            changed += 1
        conn.commit()
        return changed
    finally:
        conn.close()


def refresh(db_path: str, root_dir: str) -> Dict[str, int]:
    """Incremental update: harvest changes AND remove rows whose files are
    gone. Returns {'changed': n, 'removed': m}."""
    changed = harvest(db_path, root_dir, force=False)
    conn = _connect(db_path)
    try:
        live = {str(p) for p in _iter_part_files(root_dir)}
        gone = [row[0] for row in conn.execute("SELECT file_path FROM parts")
                if row[0] not in live]
        for fp in gone:
            conn.execute("DELETE FROM parts WHERE file_path = ?", (fp,))
        conn.commit()
        return {"changed": changed, "removed": len(gone)}
    finally:
        conn.close()


def get_part_info(db_path: str, name: str,
                  layer: Optional[str] = None) -> Dict[str, Any]:
    conn = _connect(db_path)
    try:
        q = "SELECT name, layer, purpose, meta_json, api_json, file_path FROM parts WHERE name = ?"
        args: list = [name]
        if layer is not None:
            q += " AND layer = ?"
            args.append(layer)
        row = conn.execute(q, args).fetchone()
        if row is None:
            return {}
        return {"name": row[0], "layer": row[1], "purpose": row[2],
                "meta": json.loads(row[3]), "api": json.loads(row[4]),
                "file_path": row[5]}
    finally:
        conn.close()


def list_all_parts(db_path: str) -> List[str]:
    conn = _connect(db_path)
    try:
        return [r[0] for r in conn.execute(
            "SELECT name FROM parts ORDER BY layer, name")]
    finally:
        conn.close()


def parts_in_layer(db_path: str, layer: str) -> List[Dict[str, str]]:
    conn = _connect(db_path)
    try:
        return [{"name": r[0], "purpose": r[1]} for r in conn.execute(
            "SELECT name, purpose FROM parts WHERE layer = ? ORDER BY name",
            (layer,))]
    finally:
        conn.close()


def _selftest() -> None:
    import os
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = os.path.join(tmp, "catalog.db")
        yard = Path(tmp) / "yard" / "billing"
        yard.mkdir(parents=True)
        (yard.parent / "__init__.py").write_text("", encoding="utf-8")
        (yard / "__init__.py").write_text("", encoding="utf-8")
        part_src = '''"""
invoices - test part.

### PART-META-JSON
{"name": "invoices", "layer": "billing", "purpose": "List invoices."}
### END-PART-META
"""
STATUS = "core"

def for_user(db, user_id: int) -> list:
    return []

class Invoice:
    def to_dict(self) -> dict:
        return {}
'''
        (yard / "invoices.py").write_text(part_src, encoding="utf-8")

        n = harvest(db, str(yard.parent))
        assert n == 1, f"expected 1 harvested, got {n}"
        info = get_part_info(db, "invoices")
        assert info["name"] == "invoices"
        assert info["layer"] == "billing"
        assert info["purpose"] == "List invoices."
        assert any(f.startswith("for_user(") for f in info["api"]["functions"])
        assert info["api"]["classes"][0]["name"] == "Invoice"
        assert "STATUS" in info["api"]["constants"]
        assert list_all_parts(db) == ["invoices"]
        assert parts_in_layer(db, "billing")[0]["name"] == "invoices"

        # unchanged file -> no re-harvest; changed file -> re-harvest
        assert harvest(db, str(yard.parent)) == 0
        (yard / "invoices.py").write_text(
            part_src.replace("List invoices.", "List and fetch invoices."),
            encoding="utf-8")
        r = refresh(db, str(yard.parent))
        assert r["changed"] == 1 and r["removed"] == 0
        assert get_part_info(db, "invoices")["purpose"] == "List and fetch invoices."

        # removed file -> row removed
        (yard / "invoices.py").unlink()
        r = refresh(db, str(yard.parent))
        assert r["removed"] == 1
        assert list_all_parts(db) == []


if __name__ == "__main__":
    _selftest()
