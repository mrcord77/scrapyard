"""
verify_generated_app.py — Prove a generated app is actually runnable.

Works for BOTH generation paths from ONE shared file-tree contract. Every generated
app — regardless of path — must satisfy the same structural shape:
  * a top-level main.py exposing `app`
  * an importable scrapyard/ library package
  * pinned requirements.txt + a .env.example
  * a CAPABILITIES.md metadata (common to both paths)
  * a feature/domain code package + at least one feature route
The paths differ only in *content* and a single path-specific extra each:
  * assemble (template path) -> feature code under scrapyard_app/; serves /capabilities
  * eos      (domain path)   -> domain models under scrapyard/models/; emits BUILD_REPORT.md
The common contract is asserted uniformly for both; only the one extra is flavor-gated.

Usage:  python tools/verify_generated_app.py <generated_app_dir>
Boots the app in a clean subprocess (PYTHONPATH = the app dir only) via FastAPI's
TestClient — no server needed — so a pass proves the app runs from its OWN files,
not the source tree.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys


def _probe(app_dir: str) -> dict:
    code = r'''
import json, importlib.util, os, sys, subprocess, traceback
res = {}
res["main_py_exists"] = os.path.exists("main.py")
res["requirements_exists"] = os.path.exists("requirements.txt")
res["env_example_exists"] = os.path.exists(".env.example")
# --- detect the generation flavor from the directory shape ---
if os.path.isdir("scrapyard_app"):
    flavor = "assemble"
elif os.path.isdir(os.path.join("scrapyard", "models")):
    flavor = "eos"
else:
    flavor = "unknown"
res["flavor"] = flavor
# --- COMMON file-tree contract (asserted uniformly for BOTH flavors) ---
# The two paths emit different *content* (a template app vs a domain app) but must
# satisfy the same structural shape: a top-level main:app, an importable scrapyard/
# library package, pinned requirements, a CAPABILITIES.md metadata, and a feature/
# domain code package. Only genuinely path-specific artifacts stay flavor-specific.
res["lib_pkg_exists"] = os.path.exists(os.path.join("scrapyard", "__init__.py"))
res["capabilities_md_exists"] = os.path.exists("CAPABILITIES.md")
res["feature_pkg_exists"] = os.path.isdir("scrapyard_app") or os.path.isdir(os.path.join("scrapyard", "models"))
# kept for back-compat; the common metadata is CAPABILITIES.md (present in both flavors)
res["doc_exists"] = res["capabilities_md_exists"]
res["build_report_exists"] = os.path.exists("BUILD_REPORT.md")  # eos extra

# safe dev defaults so the app can boot in isolation
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_vga_probe.db")
os.environ.setdefault("SECRET_KEY", "verify-generated-app-probe-secret-000")
# if the app ships field encryption (high/regulated domains), it requires PQ keys at
# boot — generate ephemeral ones from the app's OWN module so the boot fails for real
# reasons, not missing config.
if "PQ_FIELD_PUBLIC" not in os.environ:
    try:
        from scrapyard.security.pq_field_encryption import generate_recipient_hex
        _pk, _sk = generate_recipient_hex()
        os.environ["PQ_FIELD_PUBLIC"] = _pk; os.environ["PQ_FIELD_SECRET"] = _sk
    except Exception:
        pass

def _infra(p):
    return (p in ("/health", "/healthz", "/livez", "/readyz", "/openapi.json", "/docs",
                  "/redoc", "/capabilities", "/") or p.startswith("/auth") or p.startswith("/privacy"))

try:
    spec = importlib.util.spec_from_file_location("genmain", os.path.join(os.getcwd(), "main.py"))
    m = importlib.util.module_from_spec(spec); sys.modules["genmain"] = m; spec.loader.exec_module(m)
    app = m.app
    res["main_import"] = app is not None
    # isolation: the scrapyard package must load from the generated app dir, not source
    import scrapyard
    res["isolated"] = os.path.abspath(scrapyard.__file__).startswith(os.getcwd())
    from fastapi.testclient import TestClient
    c = TestClient(app)
    # health: accept /health or /healthz (assemble serves /health; eos serves both)
    ok_health = False
    for hp in ("/health", "/healthz"):
        try:
            if c.get(hp).status_code == 200:
                ok_health = True; break
        except Exception:
            pass
    res["health_200"] = ok_health
    # feature routes from the live OpenAPI, excluding infrastructure
    paths = list(c.get("/openapi.json").json().get("paths", {}).keys())
    feature = [p for p in paths if not _infra(p)]
    res["feature_routes_count"] = len(feature)
    res["routers_mounted"] = feature[:10]
    res["missing_expected_routes"] = []
    if flavor == "assemble":
        cp = c.get("/capabilities")
        res["capabilities_json"] = (cp.status_code == 200 and "template" in cp.json())
        capj = cp.json() if cp.status_code == 200 else {}
        res["missing_expected_routes"] = capj.get("missing_expected_routes", [])
        if "feature_routes_count" in capj:
            res["feature_routes_count"] = capj["feature_routes_count"]
    else:
        res["capabilities_json"] = True  # not applicable to the domain path
except Exception:
    res["main_import"] = False; res["main_err"] = traceback.format_exc().splitlines()[-1]
    res.setdefault("isolated", False); res.setdefault("health_200", False)
    res.setdefault("capabilities_json", False); res.setdefault("feature_routes_count", 0)
    res.setdefault("missing_expected_routes", [])

# optional behavior_check.py (assemble apps ship one; eos apps are covered by contracts)
res["behavior_check"] = None
if os.path.exists("behavior_check.py"):
    bp = subprocess.run([sys.executable, "behavior_check.py"], capture_output=True, text=True, cwd=os.getcwd())
    res["behavior_check"] = (bp.returncode == 0)
    _out = (bp.stdout + bp.stderr).strip().splitlines()
    res["behavior_out"] = _out[-1] if _out else ""
print("PROBE=" + json.dumps(res))
'''
    env = dict(os.environ, PYTHONPATH=app_dir)
    env.pop("DATABASE_URL", None)  # let the probe choose a clean per-run sqlite db
    p = subprocess.run([sys.executable, "-c", code], cwd=app_dir, env=env,
                       capture_output=True, text=True)
    line = next((l for l in p.stdout.splitlines() if l.startswith("PROBE=")), None)
    if not line:
        return {"_fatal": (p.stderr.strip().splitlines() or ["no output"])[-1]}
    return json.loads(line.split("=", 1)[1])


# common contract (asserted uniformly for BOTH flavors — structural shape, not content)
COMMON = [
    ("main.py exists", "main_py_exists"),
    ("main imports / app exists", "main_import"),
    ("app loads from generated dir (isolation)", "isolated"),
    ("health endpoint returns 200", "health_200"),
    ("requirements.txt exists", "requirements_exists"),
    (".env.example exists", "env_example_exists"),
    ("scrapyard/ library package importable", "lib_pkg_exists"),
    ("CAPABILITIES.md metadata exists", "capabilities_md_exists"),
    ("feature/domain code package present", "feature_pkg_exists"),
    ("exposes at least one feature route", "has_feature_route"),
]


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python tools/verify_generated_app.py <generated_app_dir>")
        return 2
    app_dir = os.path.abspath(argv[0])
    if not os.path.isdir(app_dir):
        print(f"not a directory: {app_dir}")
        return 2
    res = _probe(app_dir)
    if res.get("_fatal"):
        print(f"FATAL: generated app could not be probed: {res['_fatal']}")
        return 1
    res["has_feature_route"] = (res.get("feature_routes_count", 0) or 0) >= 1
    flavor = res.get("flavor", "unknown")
    print(f"  flavor: {flavor}")
    failed = []
    checks = list(COMMON)
    # flavor-specific EXTRAS (genuinely path-specific; the tree contract above is shared)
    if flavor == "assemble":
        checks += [("/capabilities returns JSON (assemble extra)", "capabilities_json")]
    elif flavor == "eos":
        checks += [("BUILD_REPORT.md exists (eos extra)", "build_report_exists")]
    else:
        print("  FAIL: unrecognized app structure (neither scrapyard_app/ nor scrapyard/models/)")
        failed.append("unknown structure")
    for label, key in checks:
        ok = bool(res.get(key))
        print(f"  {'PASS' if ok else 'FAIL'}: {label}")
        if not ok:
            failed.append(label)
            if res.get("main_err") and key == "main_import":
                print(f"        -> {res['main_err']}")
    # usefulness gate: >=1 real feature route, and (assemble) no missing expected routes
    frc = res.get("feature_routes_count", 0)
    if frc < 1:
        print("  FAIL: at least one feature route (only infrastructure routes present)")
        failed.append("no feature routes")
    else:
        print(f"  PASS: feature routes present ({frc})")
    missing = res.get("missing_expected_routes", [])
    if missing:
        print(f"  FAIL: missing expected routes -> {missing}")
        failed.append("missing expected routes")
    bc = res.get("behavior_check")
    if bc is None:
        print("  (no behavior_check.py — covered by behavior contracts)")
    elif bc:
        print(f"  PASS: behavior_check.py ({res.get('behavior_out','')})")
    else:
        print(f"  FAIL: behavior_check.py -> {res.get('behavior_out','')}")
        failed.append("behavior_check")
    print(f"  routes: {res.get('routers_mounted', []) or 'none'}")
    if failed:
        print(f"\nFAILED ({len(failed)}): {', '.join(failed)}")
        return 1
    print(f"\nPASS: generated {flavor} app is runnable (boots from its own files, health, feature routes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
