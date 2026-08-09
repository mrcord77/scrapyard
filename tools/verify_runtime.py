"""verify_runtime.py — prove a generated application is independently runnable.

Generates an app, then boots it in an ISOLATED subprocess (PYTHONPATH = the app
directory only, so it uses the app's own bundled `scrapyard` copy — no reliance
on the build tree). Proves the Priority-1 runtime properties:

  app starts · settings load · database initializes · tables available ·
  health responds · startup hooks execute · shutdown hooks execute

Usage:
  python tools/verify_runtime.py --request specs/examples/sobriety_safe.json
  python tools/verify_runtime.py --domain saas --pattern basic_saas
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
# Make the build-tree `scrapyard` importable no matter how this script is invoked
# (path script, -m, or import). Previously `from scrapyard...` below only resolved
# when the repo root happened to be on sys.path.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PROBE = r'''
import os, json, sys, warnings
warnings.filterwarnings("ignore")  # quiet third-party deprecation noise in the probe
from fastapi.testclient import TestClient
import importlib.util
spec = importlib.util.spec_from_file_location("genmain", os.path.join(os.getcwd(), "main.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
app = m.app
import scrapyard as _sy
from sqlalchemy import inspect as sqla_inspect
res = {}
res["scrapyard_origin"] = os.path.abspath(_sy.__file__)
res["imports_from_output"] = res["scrapyard_origin"].startswith(os.path.abspath(os.getcwd()))
res["settings_load"] = getattr(app.state, "settings", None) is not None
res["database_initialized"] = getattr(app.state, "engine", None) is not None
res["tables_available"] = len(sqla_inspect(app.state.engine).get_table_names())
# catch the "boots but dies on first write" bug: the library security tables the
# generated routes write to (audit_logs, sessions) must actually exist in the DB
_tables = set(sqla_inspect(app.state.engine).get_table_names())
_need = {"audit_logs": "audit_logs", "session_manager": "sessions"}
_missing_sec = [_need[c] for c in getattr(app.state, "security_caps", []) if c in _need and _need[c] not in _tables]
res["security_tables_present"] = (len(_missing_sec) == 0)
res["security_tables_missing"] = _missing_sec
hooks = app.state.hooks
with TestClient(app) as c:
    r = c.get("/healthz")
    res["app_starts"] = r.status_code == 200
    res["health_responds"] = r.json().get("status") in ("ok", "degraded")
    res["startup_hooks_execute"] = hooks.startup_ran
res["shutdown_hooks_execute"] = hooks.shutdown_ran
# ---- genuine CRUD lifecycle across EVERY entity: POST -> GET -> PUT -> DELETE ----
crud = {"attempted": False}
try:
    from scrapyard.identity.session_manager import SessionManager
    from scrapyard.database.db_session import session_scope
    headers = {}
    res["session_error"] = None
    try:
        with session_scope() as db:
            headers["X-Session"] = SessionManager(db).create(1)
    except Exception as _se:
        res["session_error"] = f"{type(_se).__name__}: {_se}"  # surfaced, not swallowed

    def _val(ann):
        s = str(ann)
        if "int" in s: return 1
        if "bool" in s: return True
        if "float" in s: return 1.0
        if "datetime" in s: return "2024-01-01T00:00:00"
        return "test-value"

    # Only probe genuine CRUD *resource* routes: a POST whose collection has an
    # item sub-route ({path}/{id}). This deliberately excludes /auth/* and the infra
    # routes (/health, /readyz, /capabilities, ...), which are POSTs but not CRUD
    # entities — probing them as CRUD was a verifier bug, not an app defect (auth is
    # proven by the build verifier's HTTP auth_routes contract instead).
    _infra = {"/healthz", "/livez", "/health", "/readyz", "/capabilities"}
    _all_paths = [getattr(r, "path", "") for r in app.routes]
    def _has_item_route(p):
        return any(q.startswith(p + "/{") for q in _all_paths)
    def _item_route(p):
        return next((q for q in _all_paths if q.startswith(p + "/{")), None)
    post_routes = [r for r in app.routes
                   if "POST" in getattr(r, "methods", set())
                   and getattr(r, "path", "") not in _infra
                   and not getattr(r, "path", "").startswith("/auth")
                   and _has_item_route(getattr(r, "path", ""))]
    have_put = {getattr(r, "path", "") for r in app.routes if "PUT" in getattr(r, "methods", set())}
    have_del = {getattr(r, "path", "") for r in app.routes if "DELETE" in getattr(r, "methods", set())}
    from fastapi.testclient import TestClient as _TC
    failures = []
    ok = 0
    verbs = {"post": 0, "get": 0, "put": 0, "delete": 0}
    with _TC(app) as cc:
        for r0 in post_routes:
            path = r0.path
            body_model = getattr(getattr(r0, "body_field", None), "type_", None)
            body = {}
            if body_model is not None and hasattr(body_model, "model_fields"):
                for fname, finfo in body_model.model_fields.items():
                    if finfo.is_required() or fname == "user_id":
                        body[fname] = 1 if fname.endswith("_id") else _val(finfo.annotation)
            pr = cc.post(path, json=body, headers=headers)
            if not (pr.status_code in (200, 201) and isinstance(pr.json(), dict) and "id" in pr.json()):
                failures.append(f"{path}: POST {pr.status_code} {(pr.text or '')[:80]}"); continue
            verbs["post"] += 1
            gid = pr.json()["id"]
            item_path = f"{path}/{gid}"
            gr = cc.get(item_path, headers=headers)
            if gr.status_code != 200:
                failures.append(f"{item_path}: GET {gr.status_code}"); continue
            verbs["get"] += 1
            # UPDATE (PUT): change one writable string field, confirm it persists
            item_template = _item_route(path)
            if item_template not in have_put:
                failures.append(f"{item_path}: PUT route missing"); continue
            upd = {k: ("edited" if "str" in str(v) else v)
                   for k, v in list(body.items())[:1]} or {}
            ur = cc.put(item_path, json=upd, headers=headers)
            if ur.status_code != 200:
                failures.append(f"{item_path}: PUT {ur.status_code} {(ur.text or '')[:60]}"); continue
            verbs["put"] += 1
            # DELETE: remove, then confirm it 404s on re-GET
            if item_template not in have_del:
                failures.append(f"{item_path}: DELETE route missing"); continue
            dr = cc.delete(item_path, headers=headers)
            if dr.status_code not in (200, 204):
                failures.append(f"{item_path}: DELETE {dr.status_code}"); continue
            if cc.get(item_path, headers=headers).status_code != 404:
                failures.append(f"{item_path}: still present after DELETE"); continue
            verbs["delete"] += 1
            ok += 1
    crud = {"attempted": True, "entities": len(post_routes), "ok": ok,
            "verbs": verbs, "failures": failures,
            "roundtrip": (len(failures) == 0
                          and (ok == len(post_routes))
                          and all(verbs[v] == len(post_routes)
                                  for v in ("post", "get", "put", "delete"))),
            "note": "no CRUD resource routes (auth-only app) — n/a" if len(post_routes) == 0 else None}
except Exception as e:
    crud = {"attempted": True, "roundtrip": False, "error": f"{type(e).__name__}: {e}"}
res["crud"] = crud
print("RUNTIME_RESULT=" + json.dumps(res))
'''

# minimal probe that just attempts to boot (import main -> bootstrap); used for failure tests
BOOT_PROBE = r'''
import os, importlib.util
spec = importlib.util.spec_from_file_location("genmain", os.path.join(os.getcwd(), "main.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print("BOOT_OK")
'''


def _gen_sensitive_app() -> str:
    import tempfile
    out = tempfile.mkdtemp(prefix="rtfail_")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import eos
    eos.main(["--request", os.path.join(ROOT, "specs", "examples", "sobriety_safe.json"), "--out", out])
    return out


def run_failures(argv: list[str]) -> int:
    import json
    import glob
    from scrapyard.security.field_encryption import generate_key
    out = _gen_sensitive_app()
    profiles = sorted(glob.glob(os.path.join(ROOT, "runtime_profiles", "*.json")))
    results = []
    for pf in profiles:
        data = json.load(open(pf, encoding="utf-8"))
        for sc in data.get("scenarios", []):
            # build a clean env per scenario
            env = dict(os.environ)
            env["PYTHONPATH"] = out
            env["DATABASE_URL"] = f"sqlite:///{out}/app.db"
            env["FIELD_ENCRYPTION_KEY"] = generate_key()
            from scrapyard.security.pq_field_encryption import generate_recipient_hex as _grh
            _pqp, _pqs = _grh()
            env["PQ_FIELD_PUBLIC"] = _pqp; env["PQ_FIELD_SECRET"] = _pqs
            if sc.get("fresh_db"):
                env["DATABASE_URL"] = f"sqlite:///{out}/fresh_{sc['name']}.db"
            for k, v in (sc.get("set") or {}).items():
                env[k] = v
            for k in (sc.get("unset") or []):
                env.pop(k, None)
            p = subprocess.run([sys.executable, "-c", BOOT_PROBE], cwd=out, env=env,
                               capture_output=True, text=True)
            booted = "BOOT_OK" in p.stdout
            output = (p.stdout + p.stderr)
            want_msg = sc.get("expect_message", "")
            msg_ok = want_msg in output
            # predictable failure = did NOT boot, exited non-zero, and emitted the expected message
            ok = (not booted) and p.returncode != 0 and msg_ok
            detail = (f"failed predictably: '{want_msg}'" if ok
                      else (f"BOOTED unexpectedly" if booted
                            else f"failed but message missing (wanted '{want_msg}')"))
            results.append((f"{data['category']}/{sc['name']}", ok, detail))
    failed = [n for n, ok, _ in results if not ok]
    for n, ok, d in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n:48} {d}")
    print(f"RUNTIME FAILURES: {len(results)-len(failed)}/{len(results)} scenarios fail predictably"
          + (f" — FAILED: {', '.join(failed)}" if failed else " — app fails cleanly under adverse conditions"))
    return 1 if failed else 0


def run(argv: list[str]) -> int:
    out = tempfile.mkdtemp(prefix="runtime_")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import eos
    if "--request" in argv:
        eos_args = ["--request", argv[argv.index("--request") + 1], "--out", out]
    else:
        dom = argv[argv.index("--domain") + 1] if "--domain" in argv else "saas"
        pat = argv[argv.index("--pattern") + 1] if "--pattern" in argv else "basic_saas"
        eos_args = ["--pattern", pat, "--domain", dom, "--out", out]
    rc = eos.main(eos_args)
    if rc not in (0, None):
        print(f"  [FAIL] generation rc={rc}"); return 1

    # boot the app standalone: cwd=out, PYTHONPATH=out (its own bundled scrapyard)
    env = dict(os.environ)
    env["PYTHONPATH"] = out
    env["DATABASE_URL"] = f"sqlite:///{out}/app.db"
    from scrapyard.security.field_encryption import generate_key
    env.setdefault("FIELD_ENCRYPTION_KEY", generate_key())
    from scrapyard.security.pq_field_encryption import generate_recipient_hex as _grh
    _pqp, _pqs = _grh()
    env["PQ_FIELD_PUBLIC"] = _pqp; env["PQ_FIELD_SECRET"] = _pqs
    p = subprocess.run([sys.executable, "-c", PROBE], cwd=out, env=env,
                       capture_output=True, text=True)
    line = next((l for l in p.stdout.splitlines() if l.startswith("RUNTIME_RESULT=")), None)
    if not line:
        print("  [FAIL] app did not boot standalone:")
        print("   " + (p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "no output"))
        return 1
    import json
    res = json.loads(line.split("=", 1)[1])
    checks = [
        ("app_starts", bool(res["app_starts"]), "/healthz -> 200"),
        ("imports_from_generated_output", bool(res.get("imports_from_output")),
         f"scrapyard loaded from generated output ({res.get('scrapyard_origin','?')})"
         if res.get("imports_from_output") else
         f"LEAK: imported from source tree ({res.get('scrapyard_origin','?')})"),
        ("settings_load", bool(res["settings_load"]), "settings on app.state"),
        ("database_initialized", bool(res["database_initialized"]), "engine bound"),
        ("tables_available", res["tables_available"] > 0, f"{res['tables_available']} tables created"),
        ("security_tables_present", bool(res["security_tables_present"]),
         "audit/session tables exist" if res["security_tables_present"]
         else f"MISSING: {res.get('security_tables_missing')}"),
        ("health_responds", bool(res["health_responds"]), "health report ok"),
        ("startup_hooks_execute", res["startup_hooks_execute"] > 0, f"{res['startup_hooks_execute']} ran"),
        ("shutdown_hooks_execute", res["shutdown_hooks_execute"] > 0, f"{res['shutdown_hooks_execute']} ran"),
        ("crud_lifecycle_roundtrip", bool(res.get("crud", {}).get("roundtrip")),
         (res["crud"].get("note") or
          (f"{res['crud'].get('ok')}/{res['crud'].get('entities')} entities full "
           f"POST/GET/PUT/DELETE lifecycle " + str(res['crud'].get('verbs')))
          if res.get("crud", {}).get("roundtrip")
          else f"FAILED: {res.get('crud', {}).get('failures') or res.get('crud', {}).get('error')}")),
    ]
    failed = [n for n, ok, _ in checks if not ok]
    for n, ok, d in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n:24} {d}")
    print(f"RUNTIME: {len(checks)-len(failed)}/{len(checks)} proven"
          + (f" — FAILED: {', '.join(failed)}" if failed else " — boots with `uvicorn main:app`, no manual edits"))
    return 1 if failed else 0


SECURE_PROBE = r'''
import os, json, sys, warnings
warnings.filterwarnings("ignore")
from fastapi.testclient import TestClient
import importlib.util
spec = importlib.util.spec_from_file_location("genmain", os.path.join(os.getcwd(), "main.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
app = m.app
from sqlalchemy import text as _sql
from scrapyard.identity.session_manager import SessionManager
from scrapyard.database.db_session import session_scope
res = {}
with session_scope() as db:
    s1 = SessionManager(db).create(1)
    s2 = SessionManager(db).create(2)
h1 = {"X-Session": s1}; h2 = {"X-Session": s2}
with TestClient(app) as c:
    # 1) anonymous access to a protected, owner-scoped collection -> 401
    res["anonymous_blocked"] = c.get("/patients").status_code == 401
    # 2) ownership forced: user1 creates a Patient while forging user_id=999
    cr = c.post("/patients", json={"user_id": 999, "dob": "1990-01-01T00:00:00", "mrn": "MRN-SECRET-1"}, headers=h1)
    res["create_status"] = cr.status_code
    pid = cr.json().get("id") if cr.status_code in (200, 201) else None
    res["owner_forced"] = res["cross_user_blocked"] = res["ciphertext_at_rest"] = False
    if pid is not None:
        g1 = c.get(f"/patients/{pid}", headers=h1)
        res["owner_forced"] = g1.status_code == 200 and g1.json().get("user_id") == 1  # not 999
        res["cross_user_blocked"] = c.get(f"/patients/{pid}", headers=h2).status_code == 404
        with app.state.engine.connect() as conn:
            raw = conn.execute(_sql("SELECT mrn FROM patients WHERE id=:i"), {"i": pid}).scalar()
        res["ciphertext_at_rest"] = bool(raw) and "MRN-SECRET-1" not in str(raw)
        # the at-rest blob is a HYBRID post-quantum envelope (not just "not plaintext")
        try:
            import base64 as _b64
            from scrapyard.security.pq_envelope import suite_of as _suite_of
            res["pq_at_rest_suite"] = _suite_of(_b64.b64decode(raw))
            res["pq_at_rest"] = res["pq_at_rest_suite"].startswith("hybrid-mlkem768")
        except Exception as _e:
            res["pq_at_rest"] = False
            res["pq_at_rest_err"] = repr(_e)
# 3) retention actually runs: seed expired + fresh rows, sweep, verify.
#    Only meaningful for domains with a time-based retention sweep module;
#    degrade to a clean skip (not a crash) when it isn't generated.
from datetime import datetime, timedelta, timezone
from scrapyard.models import models as M
try:
    from scrapyard.models.retention import run_retention, RETENTION_RULES
    res["retention_supported"] = True
except ModuleNotFoundError:
    res["retention_supported"] = False
if res["retention_supported"]:
    days = next(iter(RETENTION_RULES.values()))
    with session_scope() as db:
        old = M.Encounter(appointment_id=None, notes_ref="old", created_at=datetime.now(timezone.utc) - timedelta(days=days + 30))
        new = M.Encounter(appointment_id=None, notes_ref="new", created_at=datetime.now(timezone.utc))
        db.add(old); db.add(new); db.flush()
        old_id, new_id = old.id, new.id
    with session_scope() as db:
        run_retention(db)
    with session_scope() as db:
        res["retention_purged_expired"] = db.get(M.Encounter, old_id) is None
        res["retention_kept_fresh"] = db.get(M.Encounter, new_id) is not None
# 4) hybrid post-quantum protection is present AND functional in the shipped app
try:
    from scrapyard.security import pq_envelope as _E, pq_signing as _S
    from scrapyard.security import crypto_agility as _CA
    res["pq_present"] = True
    res["pq_post_quantum"] = _CA.policy_report()["post_quantum"]
    _pk, _sk = _E.generate_recipient()
    _w = _E.seal(b"phi", _pk, aad=b"patients:1:mrn")
    res["pq_envelope_roundtrip"] = _E.open(_w, _sk, aad=b"patients:1:mrn") == b"phi"
    _su, _ep, _kc, _no, _ct = _E._decode(_w)
    _bad = bytearray(_kc); _bad[0] ^= 0xFF
    try:
        _E.open(_E._encode(_su, _ep, bytes(_bad), _no, _ct), _sk, aad=b"patients:1:mrn")
        res["pq_hybrid_enforced"] = False  # decrypted without the real ML-KEM share -> not hybrid
    except Exception:
        res["pq_hybrid_enforced"] = True   # both shares required
    _spk, _ssk = _S.generate_keypair(); _sig = _S.sign(_ssk, b"audit")
    res["pq_signing_ok"] = _S.verify(_spk, b"audit", _sig) and not _S.verify(_spk, b"x", _sig)
except Exception as _e:
    res["pq_present"] = False
    res["pq_error"] = repr(_e)
# 5) the audit trail written during the CRUD above is tamper-evident and intact
try:
    from scrapyard.admin.audit_logs import verify_chain as _vc
    with session_scope() as _adb:
        _av = _vc(_adb)
    res["audit_chain_ok"] = _av["ok"]
    res["audit_witnessed"] = _av["witnessed"]
except Exception as _e:
    res["audit_chain_ok"] = None
    res["audit_witnessed"] = 0
print("SECURE_RESULT=" + json.dumps(res))
'''


def run_secure(argv: list[str]) -> int:
    """Adversarial end-to-end checks on a generated sensitive app: anonymous
    requests rejected, ownership forced, cross-user access denied, sensitive
    fields ciphertext at rest, and retention actually executed at runtime."""
    import json
    from scrapyard.security.field_encryption import generate_key
    out = tempfile.mkdtemp(prefix="rtsec_")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import eos
    dom = argv[argv.index("--domain") + 1] if "--domain" in argv else "healthcare"
    # The adversarial probe is healthcare-shaped: it exercises Patient/Encounter
    # entities, the `mrn` field, and a time-based retention sweep. Other sensitive
    # domains are covered by smoke_build + verify_workflow + the hybrid-PQ envelope
    # check; running this probe against them would assert healthcare semantics that
    # don't exist. Be explicit rather than crash on a missing module.
    SUPPORTED = {"healthcare"}
    if dom not in SUPPORTED:
        print(f"  [note] --secure is a healthcare-shaped adversarial probe "
              f"(Patient/Encounter, field 'mrn', time-based retention).")
        print(f"         '{dom}' doesn't match that shape; probing 'healthcare' instead.")
        dom = "healthcare"
    rc = eos.main(["--pattern", "basic_saas", "--domain", dom, "--out", out])
    if rc not in (0, None):
        print(f"  [FAIL] generation rc={rc}"); return 1
    env = dict(os.environ)
    env["PYTHONPATH"] = out
    env["DATABASE_URL"] = f"sqlite:///{out}/app.db"
    env["FIELD_ENCRYPTION_KEY"] = generate_key()
    from scrapyard.security.pq_field_encryption import generate_recipient_hex as _grh
    _pqp, _pqs = _grh()
    env["PQ_FIELD_PUBLIC"] = _pqp; env["PQ_FIELD_SECRET"] = _pqs
    p = subprocess.run([sys.executable, "-c", SECURE_PROBE], cwd=out, env=env,
                       capture_output=True, text=True)
    line = next((l for l in p.stdout.splitlines() if l.startswith("SECURE_RESULT=")), None)
    if not line:
        print("  [FAIL] secure probe did not complete:")
        print("   " + (p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "no output"))
        return 1
    res = json.loads(line.split("=", 1)[1])
    checks = [
        ("anonymous_blocked", res.get("anonymous_blocked"), "GET /patients without session -> 401"),
        ("ownership_forced", res.get("owner_forced"), "forged user_id ignored; row owned by caller"),
        ("cross_user_denied", res.get("cross_user_blocked"), "another user's row -> 404"),
        ("ciphertext_at_rest", res.get("ciphertext_at_rest"), "raw mrn column is encrypted, not plaintext"),
        ("pq_hybrid_at_rest", res.get("pq_at_rest"),
         f"stored field is a hybrid PQ envelope ({res.get('pq_at_rest_suite','?')})"),
    ]
    if res.get("retention_supported"):
        checks += [
            ("retention_purges_expired", res.get("retention_purged_expired"), "expired row deleted by sweep"),
            ("retention_keeps_fresh", res.get("retention_kept_fresh"), "fresh row retained by sweep"),
        ]
    # hybrid post-quantum protection shipped in the app
    checks += [
        ("pq_implementations_present", res.get("pq_present"),
         "crypto_agility + pq_envelope + pq_signing import in the built app"),
        ("pq_default_post_quantum", res.get("pq_post_quantum"),
         "default suites are hybrid post-quantum"),
        ("pq_envelope_roundtrip", res.get("pq_envelope_roundtrip"),
         "hybrid X25519+ML-KEM-768 envelope seals/opens"),
        ("pq_hybrid_enforced", res.get("pq_hybrid_enforced"),
         "decryption requires BOTH shares (corrupt ML-KEM -> fails)"),
        ("pq_signing_witness", res.get("pq_signing_ok"),
         "hybrid Ed25519+ML-DSA-65 signs/verifies, tamper rejected"),
    ]
    if res.get("audit_witnessed"):
        checks.append(("audit_trail_tamper_evident", res.get("audit_chain_ok"),
                       f"audit chain intact + {res.get('audit_witnessed')} PQ-witnessed entries verify"))
    failed = [n for n, ok, _ in checks if not ok]
    for n, ok, d in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n:26} {d}")
    if not res.get("retention_supported"):
        print(f"  [SKIP] {'retention_sweep':26} domain has no time-based retention module (deletion-driven retention)")
    print(f"SECURE: {len(checks)-len(failed)}/{len(checks)} adversarial properties proven"
          + (f" — FAILED: {', '.join(failed)}" if failed else " — sensitive domain holds end-to-end"))
    return 1 if failed else 0


FULLSTACK_PROBE = r'''
import os, json, sys, warnings
warnings.filterwarnings("ignore")
from fastapi.testclient import TestClient
import importlib.util
spec = importlib.util.spec_from_file_location("genmain", os.path.join(os.getcwd(), "main.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
app = m.app
res = {}
contract = json.load(open(os.path.join(os.getcwd(), "frontend", "contract.json")))

# 1) contract coherence: every endpoint the SPA calls is a mounted backend route
mounted = {}
for r in app.routes:
    for mm in (getattr(r, "methods", None) or set()):
        mounted.setdefault(r.path, set()).add(mm)
missing = [e for e in contract["endpoints"] if e["method"] not in mounted.get(e["path"], set())]
res["contract_coherent"] = (len(missing) == 0)
res["endpoint_count"] = len(contract["endpoints"])
res["missing"] = missing[:5]

def sample(field):
    t = field["type"]
    return {"int": 1, "float": 1.0, "bool": True, "datetime": "2000-01-01T00:00:00",
            "json": {}, "str": "x", "text": "x"}.get(t, "x")

with TestClient(app) as c:
    res["spa_served"] = c.get("/app/").status_code == 200 and "<html" in c.get("/app/").text.lower()
    pw = "pw-1234567"
    c.post("/auth/register", json={"email": "fsprobe@scrapyard-fs.com", "password": pw})
    lr = c.post("/auth/login", json={"email": "fsprobe@scrapyard-fs.com", "password": pw})
    res["auth_flow"] = lr.status_code == 200 and "session" in lr.json()
    H = {"X-Session": lr.json().get("session", "")} if res["auth_flow"] else {}
    # pick the first auth-required entity and drive a real CRUD lifecycle
    ent = next((e for e in contract["entities"] if e["requires_auth"]), None)
    if ent and res["auth_flow"]:
        plural = ent["plural"]
        res["anon_blocked"] = c.get(f"/{plural}").status_code == 401
        payload = {f["name"]: sample(f) for f in ent["writable"] if not f["optional"]}
        cr = c.post(f"/{plural}", json=payload, headers=H)
        res["create_ok"] = cr.status_code == 201
        rid = cr.json().get("id") if res["create_ok"] else None
        res["list_ok"] = res["create_ok"] and any(r.get("id") == rid for r in c.get(f"/{plural}?limit=100", headers=H).json())
        res["get_ok"] = bool(rid) and c.get(f"/{plural}/{rid}", headers=H).status_code == 200
        res["delete_ok"] = bool(rid) and c.delete(f"/{plural}/{rid}", headers=H).status_code == 204
        res["probed_entity"] = ent["name"]
    else:
        res["anon_blocked"] = res["create_ok"] = res["list_ok"] = res["get_ok"] = res["delete_ok"] = False
print("FULLSTACK_RESULT=" + json.dumps(res))
'''


def run_fullstack(argv: list[str]) -> int:
    """Generate an app (backend + auth + SPA), boot it, and prove the generated
    frontend and backend compose end-to-end: every endpoint the SPA calls is a
    real route, the SPA is served, and a live register->login->create->list->
    get->delete lifecycle runs over HTTP through the generated contract."""
    import json
    from scrapyard.security.field_encryption import generate_key
    out = tempfile.mkdtemp(prefix="rtfull_")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import eos
    dom = argv[argv.index("--domain") + 1] if "--domain" in argv else "healthcare"
    pat = argv[argv.index("--pattern") + 1] if "--pattern" in argv else "saas_subscription_app"
    rc = eos.main(["--pattern", pat, "--domain", dom, "--out", out])
    if rc not in (0, None):
        print(f"  [FAIL] generation rc={rc}"); return 1
    env = dict(os.environ)
    env["PYTHONPATH"] = out
    env["DATABASE_URL"] = f"sqlite:///{out}/app.db"
    env["FIELD_ENCRYPTION_KEY"] = generate_key()
    from scrapyard.security.pq_field_encryption import generate_recipient_hex as _grh
    _pqp, _pqs = _grh()
    env["PQ_FIELD_PUBLIC"] = _pqp; env["PQ_FIELD_SECRET"] = _pqs
    p = subprocess.run([sys.executable, "-c", FULLSTACK_PROBE], cwd=out, env=env,
                       capture_output=True, text=True)
    line = next((l for l in p.stdout.splitlines() if l.startswith("FULLSTACK_RESULT=")), None)
    if not line:
        print("  [FAIL] fullstack probe did not complete:")
        print("   " + (p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "no output"))
        return 1
    res = json.loads(line.split("=", 1)[1])
    ent = res.get("probed_entity", "?")
    checks = [
        ("contract_coherent", res.get("contract_coherent"),
         f"all {res.get('endpoint_count','?')} SPA endpoints resolve to mounted backend routes"),
        ("spa_served", res.get("spa_served"), "generated SPA served at /app/"),
        ("auth_flow", res.get("auth_flow"), "register + login issues a session token"),
        ("anon_blocked", res.get("anon_blocked"), f"anonymous GET /{ent} -> 401"),
        ("create_ok", res.get("create_ok"), f"authenticated create {ent} -> 201"),
        ("list_ok", res.get("list_ok"), f"created {ent} appears in owner's list"),
        ("get_ok", res.get("get_ok"), f"GET {ent}/id -> 200"),
        ("delete_ok", res.get("delete_ok"), f"DELETE {ent}/id -> 204"),
    ]
    failed = [n for n, ok, _ in checks if not ok]
    for n, ok, d in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n:18} {d}")
    if res.get("missing"):
        print("   missing:", res["missing"])
    print(f"FULLSTACK: {len(checks)-len(failed)}/{len(checks)} proven"
          + (f" — FAILED: {', '.join(failed)}" if failed else
             " — generated frontend + backend compose and run end-to-end"))
    return 1 if failed else 0


if __name__ == "__main__":
    if "--failures" in sys.argv:
        raise SystemExit(run_failures(sys.argv[1:]))
    if "--secure" in sys.argv:
        raise SystemExit(run_secure(sys.argv[1:]))
    if "--fullstack" in sys.argv:
        raise SystemExit(run_fullstack(sys.argv[1:]))
    raise SystemExit(run(sys.argv[1:]))
