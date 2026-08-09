"""
dependency_closure.py — Copy the REAL transitive import closure of an assembled app.

The capability-graph closure only follows declared `requires` edges, so a bare
`import scrapyard.x` inside a function (e.g. users.create() importing
password_policy) is invisible to it — the app boots but crashes when that code path
runs. This walks the actual Python imports with `ast` (every node, including
function-body imports) and copies every referenced scrapyard file, transitively,
until no new local imports remain. That makes the copied tree import-complete under
behavior, not just at module load.
"""
from __future__ import annotations
import ast
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "scrapyard")


def discover_scrapyard_imports(py_path: str) -> set[str]:
    """All `scrapyard.*` modules imported anywhere in the file (top-level OR inside
    functions — ast.walk visits every node)."""
    try:
        tree = ast.parse(open(py_path, encoding="utf-8").read())
    except Exception:
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("scrapyard."):
                    mods.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("scrapyard.") and (node.level or 0) == 0:
                mods.add(node.module)
    return mods


def module_to_repo_file(module: str) -> str | None:
    """Resolve a scrapyard module to its source file in the repo (module.py, or the
    package __init__.py)."""
    rel = module.replace(".", "/")
    cand = os.path.join(ROOT, rel + ".py")
    if os.path.exists(cand):
        return cand
    initp = os.path.join(ROOT, rel, "__init__.py")
    if os.path.exists(initp):
        return initp
    return None


def _copy_into(out_dir: str, repo_file: str) -> None:
    rel = os.path.relpath(repo_file, ROOT)          # e.g. scrapyard/security/password_policy.py
    dst = os.path.join(out_dir, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy(repo_file, dst)
    # ensure every package __init__ along the path exists
    parts = rel.split(os.sep)
    for i in range(1, len(parts)):
        pkg_init_repo = os.path.join(ROOT, *parts[:i], "__init__.py")
        pkg_init_dst = os.path.join(out_dir, *parts[:i], "__init__.py")
        if os.path.exists(pkg_init_repo) and not os.path.exists(pkg_init_dst):
            os.makedirs(os.path.dirname(pkg_init_dst), exist_ok=True)
            shutil.copy(pkg_init_repo, pkg_init_dst)


def expand_dependency_closure(out_dir: str) -> dict:
    """Walk every scrapyard/*.py already in out_dir, follow all scrapyard imports
    transitively, and copy any missing source files in. Returns {added, scanned,
    unresolved}."""
    pkg_out = os.path.join(out_dir, "scrapyard")
    seen: set[str] = set()
    added: list[str] = []
    unresolved: set[str] = set()

    def file_to_module(path: str) -> str:
        rel = os.path.relpath(path, out_dir)[:-3]   # strip .py
        return rel.replace(os.sep, ".")

    # seed with whatever was already copied
    queue: list[str] = []
    for dirpath, _, files in os.walk(pkg_out):
        for f in files:
            if f.endswith(".py"):
                queue.append(os.path.join(dirpath, f))

    scanned = 0
    while queue:
        py = queue.pop()
        mod = file_to_module(py)
        if mod in seen:
            continue
        seen.add(mod)
        scanned += 1
        for dep in discover_scrapyard_imports(py):
            if dep in seen:
                continue
            dst = os.path.join(out_dir, dep.replace(".", "/") + ".py")
            dst_init = os.path.join(out_dir, dep.replace(".", "/"), "__init__.py")
            if os.path.exists(dst) or os.path.exists(dst_init):
                continue  # already present
            repo_file = module_to_repo_file(dep)
            if not repo_file:
                unresolved.add(dep)
                continue
            _copy_into(out_dir, repo_file)
            added.append(dep)
            queue.append(os.path.join(out_dir, os.path.relpath(repo_file, ROOT)))

    return {"added": sorted(added), "scanned": scanned, "unresolved": sorted(unresolved)}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python tools/dependency_closure.py <assembled_app_dir>")
        raise SystemExit(2)
    r = expand_dependency_closure(sys.argv[1])
    print(f"closure: +{len(r['added'])} files copied, {r['scanned']} scanned"
          + (f", UNRESOLVED: {r['unresolved']}" if r["unresolved"] else ""))
    for m in r["added"]:
        print("  +", m)
