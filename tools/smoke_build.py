#!/usr/bin/env python3
"""
smoke_build.py — prove an assembled app actually boots.

Materializes a plan to a temp dir, generates + wires the model layer, then in an
isolated subprocess: imports the app, builds the FastAPI app with the generated
routers mounted, asserts health + generated routes exist, and creates the model
tables against in-memory SQLite. Finishes with validation + enforcement checks.

    python tools/smoke_build.py <pattern> [--domain d] [--stage s] [--include a,b] [--exclude a,b]
"""
from __future__ import annotations
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)

BOOT = r'''
import sys
from scrapyard.api.app_factory import create_app
from sqlalchemy import create_engine
ok = []
try:
    from scrapyard.models.models import Base
    from scrapyard.models.routes import router as mr
    eng = create_engine("sqlite:///:memory:"); Base.metadata.create_all(eng)
    ok.append("models import + create_all")
    app = create_app(routers=[mr])
    paths = {r.path for r in app.routes}
    assert "/healthz" in paths, "health route missing"
    gen = [p for p in paths if p not in ("/healthz","/livez","/openapi.json","/docs","/redoc","/docs/oauth2-redirect")]
    assert gen, "no generated routes mounted"
    ok.append(f"app boots; {len(gen)} generated routes mounted")
except Exception as e:
    print("BOOT FAIL:", type(e).__name__, e); sys.exit(1)
print("BOOT OK — " + "; ".join(ok))
'''


def main(argv):
    if not argv:
        print(__doc__); return 2
    import resolve as R, validate_assembly as VA
    plan = R.plan_from_args(argv)
    if not plan:
        print(f"unknown pattern: {argv[0]}"); return 1

    tmp = tempfile.mkdtemp(prefix="smoke_")
    env = dict(os.environ, PYTHONPATH=ROOT)
    # materialize honoring include/exclude
    mat = list(argv) + ["--out", tmp]
    subprocess.run([PY, os.path.join(TOOLS, "resolve.py"), *mat],
                   capture_output=True, text=True, env=env, cwd=ROOT)
    # generate + wire models if a domain is present
    if plan["domain_name"]:
        subprocess.run([PY, os.path.join(TOOLS, "gen_models.py"), plan["domain_name"],
                        os.path.join(tmp, "scrapyard", "models"), "--wire"],
                       capture_output=True, text=True, env=env, cwd=ROOT)

    checks = []
    # boot check in isolated subprocess against the materialized app
    if plan["domain_name"]:
        boot = os.path.join(tmp, "_boot.py")
        open(boot, "w", encoding="utf-8").write(BOOT)
        r = subprocess.run([PY, boot], capture_output=True, text=True,
                           env=dict(os.environ, PYTHONPATH=tmp), cwd=tmp)
        line = (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "no output"
        checks.append(("boot", r.returncode == 0, line))
    else:
        checks.append(("boot", True, "no domain models to wire (skipped)"))

    # validation
    findings = VA.run_rules(plan["part_caps"], stage=plan["stage"], res=plan["res"],
                            graph_stage_of=(R.load_stages()["stage_of"] if plan["stage"] else None))
    val_ok = not any(s == "FAIL" for _, s, _ in findings)
    checks.append(("validation", val_ok, "no FAIL rules" if val_ok else "validation FAILs present"))

    # enforcement
    inc_ok = all(c in plan["part_caps"] for c in plan["include"])
    exc_ok = all(c not in plan["part_caps"] for c in plan["exclude"])
    checks.append(("must_have", inc_ok, str(plan["include"] or "none")))
    checks.append(("must_not", exc_ok, str(plan["exclude"] or "none")))

    print(f"SMOKE BUILD: {plan['pattern_name']}"
          + (f"+{plan['domain_name']}" if plan["domain_name"] else "")
          + (f" @{plan['stage']}" if plan["stage"] else ""))
    allok = True
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:11} {detail}")
        allok = allok and ok
    print(f"  => {'SMOKE OK' if allok else 'SMOKE FAILED'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
