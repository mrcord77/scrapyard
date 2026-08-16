#!/usr/bin/env python3
"""
assemble.py — compose a product template into a fresh app.

A template is templates/<name>/template.json:
    { "description": "...", "parts": ["scrapyard.foundation.config", ...] }

This copies each listed part (and its layer __init__) into <out>/scrapyard/...,
writes a requirements.txt from the union of the parts' declared dependencies,
and drops a START.md describing what remains to be wired.

    python tools/assemble.py <template_name> <out_dir>
    python tools/assemble.py --list
"""
from __future__ import annotations
try:
    import _bootstrap_path  # noqa: F401  (puts repo root on sys.path)
except ModuleNotFoundError:  # imported as tools.<mod>, not run as a script
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import _bootstrap_path  # noqa: F401
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "scrapyard")
TPL = os.path.join(ROOT, "templates")
CAT = os.path.join(ROOT, "catalog.json")


def load_catalog() -> dict:
    with open(CAT, encoding="utf-8") as f:
        return json.load(f)


def index_by_import(cat: dict) -> dict[str, dict]:
    out = {}
    for items in cat["layers"].values():
        for p in items:
            out[p["import_path"]] = p
    return out


def list_templates() -> None:
    if not os.path.isdir(TPL):
        print("no templates/ dir")
        return
    for name in sorted(os.listdir(TPL)):
        tj = os.path.join(TPL, name, "template.json")
        if os.path.exists(tj):
            d = json.load(open(tj, encoding="utf-8"))
            print(f"  {name:16} {d.get('description','')} ({len(d.get('parts',[]))} parts)")


def assemble_parts(part_import_paths, out: str, *, name: str, description: str = "",
                   extra_notes: str = "") -> dict:
    """Copy the given part import-paths (and their layer __init__) into <out>.

    Shared by template assembly and the capability resolver. Returns a summary
    dict: {copied, missing, deps}. Only PYTHON deps go into requirements.txt;
    frontend deps (react, etc.) are listed separately in START.md.
    """
    NON_PIP = {"react", "react-dom", "next", "tailwindcss", "vite"}
    # import-name -> pip-name for modules parts actually import at module scope.
    # Declared metadata deps are trusted but INCOMPLETE in practice (2026-08-16
    # audit: 197/582 parts import third-party modules they never declare — an
    # app only booted because some OTHER part declared the package). The writer
    # closes the gap by scanning the copied sources.
    IMPORT_TO_PIP = {
        "httpx": "httpx", "pydantic": "pydantic", "pydantic_core": "pydantic",
        "sqlalchemy": "sqlalchemy", "fastapi": "fastapi", "starlette": "fastapi",
        "jinja2": "jinja2", "redis": "redis", "stripe": "stripe", "jwt": "pyjwt",
        "passlib": "passlib[argon2]", "argon2": "argon2-cffi", "bleach": "bleach",
        "alembic": "alembic", "yaml": "pyyaml", "cryptography": "cryptography",
        "psycopg2": "psycopg2-binary", "email_validator": "email-validator",
        "dilithium_py": "dilithium-py", "kyber_py": "kyber-py", "uvicorn": "uvicorn",
        "sentry_sdk": "sentry-sdk", "authlib": "authlib", "joserfc": "joserfc",
        "markdown": "markdown", "multipart": "python-multipart",
    }
    by_ip = index_by_import(load_catalog())
    os.makedirs(os.path.join(out, "scrapyard"), exist_ok=True)
    shutil.copy(os.path.join(PKG, "__init__.py"), os.path.join(out, "scrapyard", "__init__.py"))
    deps: set[str] = set()
    js_deps: set[str] = set()
    copied: list[str] = []
    missing: list[str] = []
    for ip in part_import_paths:
        p = by_ip.get(ip)
        if not p:
            missing.append(ip)
            continue
        src = os.path.join(ROOT, p["file"].replace("/", os.sep))
        layer = p["import_path"].split(".")[1]
        ldir = os.path.join(out, "scrapyard", layer)
        os.makedirs(ldir, exist_ok=True)
        li = os.path.join(PKG, layer, "__init__.py")
        if os.path.exists(li):
            shutil.copy(li, os.path.join(ldir, "__init__.py"))
        shutil.copy(src, os.path.join(ldir, os.path.basename(src)))
        for d in p.get("dependencies", []):
            if d.startswith("scrapyard."):
                continue  # internal module, not a pip package (closure copies the file)
            (js_deps if d in NON_PIP else deps).add(d)
        copied.append(ip)
    # close the declared-vs-actual gap: scan copied sources for module-level
    # third-party imports and union the known pip names into requirements.
    import ast as _ast
    import sys as _sys
    _stdlib = set(_sys.stdlib_module_names)
    for dirpath, _, files in os.walk(os.path.join(out, "scrapyard")):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            try:
                tree = _ast.parse(open(os.path.join(dirpath, fn), encoding="utf-8",
                                       errors="ignore").read())
            except SyntaxError:
                continue
            for node in tree.body:
                mods = []
                if isinstance(node, _ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, _ast.ImportFrom) and node.module and node.level == 0:
                    mods = [node.module.split(".")[0]]
                for m in mods:
                    if m in _stdlib or m == "scrapyard":
                        continue
                    pip = IMPORT_TO_PIP.get(m)
                    if pip:
                        deps.add(pip)
    with open(os.path.join(out, "requirements.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(deps)) + ("\n" if deps else ""))
    with open(os.path.join(out, "START.md"), "w", encoding="utf-8") as f:
        f.write(f"# {name} — assembled app\n\n{description}\n\n")
        if extra_notes:
            f.write(extra_notes + "\n\n")
        f.write("## Included parts\n" + "".join(f"- `{ip}`\n" for ip in copied))
        if js_deps:
            f.write("\n## Frontend deps (npm, not in requirements.txt)\n"
                    + "".join(f"- `{d}`\n" for d in sorted(js_deps)))
        if missing:
            f.write("\n## MISSING (not in catalog — check names)\n"
                    + "".join(f"- `{ip}`\n" for ip in missing))
        # Report the VERIFIED status of each copied part straight from the
        # catalog's verification fields (computed by tools/index_catalog.py:
        # metadata_ok + imports_ok + no hollow NotImplementedError). Nothing
        # here asserts the catalog is "fully implemented" — the fields say
        # exactly what was verified and what was not.
        verified_core: list[str] = []
        not_verified: list[tuple[str, str]] = []
        unverified_catalog = False
        for ip in copied:
            p = by_ip.get(ip, {})
            if "imports_ok" not in p:  # old-format catalog: no verified fields
                unverified_catalog = True
                continue
            if p.get("status") == "core":
                verified_core.append(ip)
            else:
                why = "; ".join(p.get("reasons", [])) or "not verified as core"
                not_verified.append((ip, why))
        f.write("\n## Verified status of copied parts\n")
        if unverified_catalog:
            f.write("- catalog.json predates verification — rerun "
                    "`python tools/index_catalog.py` for verified statuses.\n")
        else:
            f.write(f"- {len(verified_core)} of {len(copied)} copied parts are "
                    "verified core (metadata present, imports OK, no hollow "
                    "NotImplementedError) per tools/index_catalog.py.\n")
            for ip, why in not_verified:
                f.write(f"- NOT verified: `{ip}` — {why}\n")
        f.write("\n## Next\n1. `pip install -r requirements.txt`\n"
                "2. Run the app: `DATABASE_URL=sqlite:///./app.db uvicorn main:app --reload`\n")
        if not_verified:
            f.write(f"3. Review the {len(not_verified)} unverified part(s) above "
                    "before relying on them.\n")
    return {"copied": copied, "missing": missing, "deps": sorted(deps)}


def _copy_runtime_support(out: str) -> None:
    """Copy non-catalog runtime infra the generated entrypoint relies on
    (fallback gate). Best-effort; the generated bootstrap guards these imports."""
    for rel in ["runtime/__init__.py", "runtime/fallbacks.py", "runtime/request_security.py",
                "database/metadata.py",
                "security/row_level_security.py", "security/rate_limiting.py",
                "operations/__init__.py",
                "operations/readiness.py", "operations/backup.py",
                "observability/__init__.py", "observability/error_reporting.py",
                "observability/tracing.py"]:
        src = os.path.join(PKG, rel)
        if os.path.exists(src):
            dst = os.path.join(out, "scrapyard", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(src, dst)


def assemble(name: str, out: str) -> int:
    tj = os.path.join(TPL, name, "template.json")
    if not os.path.exists(tj):
        print(f"unknown template: {name} (try --list)")
        return 1
    spec = json.load(open(tj, encoding="utf-8"))
    template_parts = spec.get("parts", [])

    # Dependency CLOSURE: copying only the template's listed parts leaves imports
    # dangling (e.g. auth_routes needs session_manager). Resolve the transitive
    # closure over the capability graph so the copied set is import-complete, and
    # force-include the foundation needed to boot a real app.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import resolve as R
    graph = R.load_graph()
    part_to_cap = {c["part"]: cap for cap, c in graph["concrete"].items()}
    wanted = [part_to_cap[ip] for ip in template_parts if ip in part_to_cap]
    wanted += ["app_factory", "db_session", "base_model", "health",
               "request_context", "error_handling", "config", "logging_setup"]
    res = R.resolve_capabilities(graph, wanted)
    closure = sorted(res["parts"].keys())

    r = assemble_parts(closure, out, name=name, description=spec.get("description", ""),
                       extra_notes="Dependency closure resolved — the copied set is import-complete.")
    _copy_runtime_support(out)

    # REAL import closure: the graph only knows declared `requires` edges, so a bare
    # import inside a function (users.create -> security.password_policy) is invisible
    # to it. AST-trace every actual scrapyard import and copy what's missing, so the
    # app is import-complete under behavior, not just at module load.
    from dependency_closure import expand_dependency_closure
    cl = expand_dependency_closure(out)
    if cl["added"]:
        # the closure pulled in files the graph didn't list — union their declared
        # pip deps into requirements.txt so a clean `pip install` is complete too.
        by_ip = index_by_import(load_catalog())
        existing = set()
        req_path = os.path.join(out, "requirements.txt")
        if os.path.exists(req_path):
            existing = {l.strip() for l in open(req_path, encoding="utf-8") if l.strip()}
        NON_PIP = {"react", "react-dom", "next", "tailwindcss", "vite"}
        for mod in cl["added"]:
            p = by_ip.get(mod)
            if p:
                for d in p.get("dependencies", []):
                    if d not in NON_PIP:
                        existing.add(d)
        open(req_path, "w", encoding="utf-8").write("\n".join(sorted(existing)) + ("\n" if existing else ""))
        print(f"  import-closure: +{len(cl['added'])} files the graph missed "
              f"({', '.join(cl['added'][:4])}{'…' if len(cl['added']) > 4 else ''})")
    if cl["unresolved"]:
        print(f"  WARNING: unresolved imports: {cl['unresolved']}")

    # Generate the runnable entrypoint (main.py + scrapyard_app/* + env + smoke + caps)
    from generate_runtime_app import generate_runtime_app
    g = generate_runtime_app(out, name, r["copied"])
    missing_rt = [f for f in g["written"] if not os.path.exists(os.path.join(out, f))]
    if missing_rt:
        print(f"ERROR: assembly did not produce a runnable app — missing {missing_rt}")
        return 3

    # L5: write a real, production-wired deployment (Dockerfile/compose/.env)
    from gen_deployment import write_deployment
    dep = write_deployment(out)
    # L6/L11/CDN: write validatable infrastructure-as-code
    from gen_infra import write_infra
    infra = write_infra(out)
    # L1: write a real Vite + React frontend over the proven API
    from gen_frontend_react import write_react_frontend
    fe = write_react_frontend(out)

    print(f"assembled '{name}' -> {out}  ({len(r['copied'])} parts incl. closure, "
          f"{len(r['deps'])} deps, {len(g['routers'])} router(s) wired"
          + (f", {len(r['missing'])} MISSING" if r["missing"] else "") + ")")
    print(f"  deployment: {', '.join(dep['written'])}")
    print(f"  infra: {', '.join(infra['written'])}")
    print(f"  frontend: Vite+React ({len(fe['written'])} files) — cd frontend && npm install && npm run build")
    print(f"  runnable: pip install -r requirements.txt && python smoke_check.py && uvicorn main:app")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "--list":
        list_templates()
        return 0
    if len(argv) < 2:
        print(__doc__)
        return 2
    return assemble(argv[0], argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
