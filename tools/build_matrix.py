"""
build_matrix.py — Release gate: every template must assemble into a *useful* app.

For each template: assemble -> verify_generated_app -> smoke_check -> behavior_check
-> verify_frontend (headless Chrome render + rubric), printing a PASS/FAIL matrix.
Exits nonzero if any template fails any column. A stub frontend FAILS the gate with
the same weight as a backend failure.

Usage: python tools/build_matrix.py [--keep] [--skip-frontend] [template ...]
"""
from __future__ import annotations
try:
    import _bootstrap_path  # noqa: F401  (puts repo root on sys.path)
except ModuleNotFoundError:  # imported as tools.<mod>, not run as a script
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import _bootstrap_path  # noqa: F401
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, "templates")
PY = sys.executable


def _templates() -> list[str]:
    return sorted(d for d in os.listdir(TPL)
                  if os.path.isdir(os.path.join(TPL, d))
                  and os.path.exists(os.path.join(TPL, d, "template.json")))


def _run(cmd, cwd=None, env=None, timeout=180) -> tuple[bool, str]:
    # Hard per-step timeout: a generated app that blocks at boot (a network wait,
    # a port bind, an LLM client without a key) must fail this step, not hang the
    # whole matrix forever. A timeout is reported as a failure with the step name.
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout + p.stderr)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "") if isinstance(e.stdout, str) else ""
        return False, f"TIMEOUT after {timeout}s: {' '.join(cmd)}\n{out}"


def main(argv: list[str]) -> int:
    keep = "--keep" in argv
    skip_fe = "--skip-frontend" in argv
    wanted = [a for a in argv if not a.startswith("--")] or _templates()
    env = dict(os.environ, PYTHONPATH=ROOT, PYTHONUTF8="1")
    rows = []
    any_fail = False
    for t in wanted:
        out = tempfile.mkdtemp(prefix=f"matrix_{t}_")
        asm, _ = _run([PY, os.path.join("tools", "assemble.py"), t, out], cwd=ROOT, env=env, timeout=180)
        ver = smoke = beh = fe = False
        if asm:
            ver, vmsg = _run([PY, os.path.join("tools", "verify_generated_app.py"), out], cwd=ROOT, env=env, timeout=120)
            app_env = dict(os.environ, PYTHONPATH=out, PYTHONUTF8="1")
            smoke, smsg = _run([PY, "smoke_check.py"], cwd=out, env=app_env, timeout=90)
            beh_msg = ""
            if os.path.exists(os.path.join(out, "behavior_check.py")):
                beh, beh_msg = _run([PY, "behavior_check.py"], cwd=out, env=app_env, timeout=90)
            for _m in (vmsg, smsg, beh_msg):
                if isinstance(_m, str) and _m.startswith("TIMEOUT"):
                    print(f"  [{t}] {_m.splitlines()[0]}")
            if not skip_fe:
                fe_script = os.path.join("tools", "verify_frontend.py")
                fe_out = os.path.join(out, "frontend_gate.png")
                fe, fe_msg = _run([PY, fe_script, out, "--out", fe_out], cwd=ROOT, env=env, timeout=120)
                if not fe and fe_msg:
                    lines = [l for l in fe_msg.splitlines() if "FAIL" in l or "HARD FAIL" in l]
                    if not lines:
                        lines = [l for l in fe_msg.splitlines() if l.strip()][-5:]
                    for l in lines[:5]:
                        print(f"  [{t}] frontend: {l.strip()}")
            else:
                fe = True  # skipped = neutral (doesn't block)
        row = (t, asm, ver, smoke, beh, fe)
        rows.append(row)
        if not all([asm, ver, smoke, beh, fe]):
            any_fail = True
        if not keep:
            import shutil; shutil.rmtree(out, ignore_errors=True)

    def cell(b): return "PASS" if b else "FAIL"
    w = max(len(t) for t, *_ in rows)
    hdr = f"{'Template'.ljust(w)}  Assemble  Verify  Smoke  Behavior  Frontend"
    print(hdr)
    for t, a, v, s, b, f in rows:
        print(f"{t.ljust(w)}  {cell(a).ljust(8)}  {cell(v).ljust(6)}  {cell(s).ljust(5)}  {cell(b).ljust(8)}  {cell(f)}")
    print()
    if any_fail:
        print("BUILD MATRIX: FAIL — at least one template is not a working app.")
        return 1
    print("BUILD MATRIX: PASS — every template assembles into a working app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
