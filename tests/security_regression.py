"""Security regression harness: reproduces the 5 exploits an automated
Codex adversarial review found (2026-08-09) and asserts each stays CLOSED. Run:
    py tests/security_regression.py
Exit 0 = all closed; nonzero = a regression reopened one."""
import os, sys, time, importlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
results = []
def check(name, fn):
    try:
        fn(); results.append((name, "CLOSED", ""))
    except AssertionError as e:
        results.append((name, "STILL OPEN", str(e)))
    except Exception as e:  # noqa: BLE001
        results.append((name, "ERROR", f"{type(e).__name__}: {e}"))

# 1. JWT revocation bypass via base64 padding
def jwt_exploit():
    j = importlib.import_module("scrapyard.identity.jwt_manager")
    sec = "security-regression-key-32-bytes-minimum"
    tok = j.encode_token("alice", sec)
    j.revoke_token(tok, sec)
    assert j.is_token_revoked(tok, sec), "base token not revoked"
    for pad in ("=", "=="):
        v = tok + pad
        assert j.is_token_revoked(v, sec), f"padded variant {pad!r} not revoked"
        assert j.introspect(v, sec) is None, f"introspect accepted padded {pad!r}"
        try:
            j.decode_token(v, sec); raise AssertionError(f"decode accepted padded {pad!r}")
        except AssertionError: raise
        except Exception: pass  # decode raising is the correct (revoked) behavior
check("JWT revocation padding bypass", jwt_exploit)

# 2. PQ signature downgrade against a hybrid key
def pq_exploit():
    pq = importlib.import_module("scrapyard.security.pq_signing")
    pub, sec = pq.generate_keypair()
    msg = b"transfer 1000 to attacker"
    good = pq.sign(sec, msg)
    assert pq.verify(pub, msg, good), "legit hybrid signature failed to verify"
    # downgrade: produce a classical-ed25519-only signature (no PQ component)
    downgraded = pq.sign(sec, msg, suite_id="classical-ed25519")
    assert pq.verify(pub, msg, downgraded) is False, \
        "DOWNGRADE ACCEPTED: classical-only signature verified against hybrid key"
check("PQ signing downgrade", pq_exploit)

# 3. CSRF middleware honors its own secret
def csrf_exploit():
    c = importlib.import_module("scrapyard.security.csrf")
    sid = "sess-1"
    tok_a = c.issue_token("secretA", sid)
    assert c.validate_token(tok_a, "secretA", sid) is True, "own-secret token rejected"
    assert c.validate_token(tok_a, "secretB", sid) is False, "token validated under wrong secret"
check("CSRF secret honored", csrf_exploit)

# 4. signed_cookies policy round-trip + expiration
def cookie_exploit():
    sc = importlib.import_module("scrapyard.security.signed_cookies")
    try:
        pol = sc.PolicyConfig(expiration=1)
    except TypeError:
        pol = sc.PolicyConfig(); object.__setattr__(pol, "expiration", 1)
    tok = sc.sign_with_policy({"uid": 7, "role": "user"}, "k", pol)
    got = sc.unsign_with_policy(tok, "k", pol)
    assert got and got.get("uid") == 7, f"round-trip failed: {got!r}"
    assert "_sc_iat" not in got, "internal issue-time leaked to caller"
    assert sc.unsign_with_policy(tok + "x", "k", pol) is None, "tampered cookie accepted"
    time.sleep(1.2)
    assert sc.unsign_with_policy(tok, "k", pol) is None, "expired cookie accepted"
check("signed_cookies policy+expiry", cookie_exploit)

# 5. AST evaluators reject hostile context objects (no dunder invocation)
def ast_exploit():
    mods = {
        "quoting.discount_rule": "safe_eval_condition",
        "agents.stop_condition_checker": "_safe_eval_condition",
        "approvals_workfl.approval_policy": "_safe_eval_condition",
        "expenses.policy_validation": "_safe_eval_condition",
        "hr_lite_onboardi.compliance_checker": "_safe_eval_condition",
        "support.pause_condition": "_safe_eval_condition",
    }
    for mod, fn_name in mods.items():
        m = importlib.import_module(f"scrapyard.{mod}")
        fn = getattr(m, fn_name)
        class Hostile:
            invoked = False
            def __add__(self, o): Hostile.invoked = True; return 0
            def __gt__(self, o): Hostile.invoked = True; return True
            def __bool__(self): Hostile.invoked = True; return True
        # also a PRIMITIVE SUBCLASS that overrides an operator — isinstance() would
        # wrongly admit this; only an exact-type guard rejects it (Codex 2026-08-09).
        class EvilInt(int):
            invoked = False
            def __add__(self, o): EvilInt.invoked = True; return 0
        for label, obj, flagcls in (("plain", Hostile(), Hostile), ("int-subclass", EvilInt(3), EvilInt)):
            try:
                fn("x + 1 > 5", {"x": obj})
                raise AssertionError(f"{mod}: hostile {label} object not rejected")
            except AssertionError: raise
            except Exception: pass  # ValueError expected
            assert flagcls.invoked is False, f"{mod}: a dunder fired on the hostile {label} object"
check("AST evaluators reject hostile objects (6)", ast_exploit)

# 8. DSAR export must not leak credentials (password hash / live session token).
# (2026-08-16 factory campaign: /privacy/export contained the argon2 hash AND
# the caller's active plaintext session token.)
def export_leak_exploit():
    # subprocess: the part selftest asserts hash+token redaction; an in-process
    # run would collide with other tests on the shared declarative registry.
    import subprocess
    p = subprocess.run([sys.executable, "-m", "scrapyard.compliance.data_export"],
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert p.returncode == 0, f"data_export selftest failed: {p.stderr[-400:]}"
    assert "passed" in p.stdout
check("DSAR export credential leak", export_leak_exploit)

# 7. Generated CAPABILITIES.md must not overstate route security.
# (2026-08-16 factory campaign: low-sensitivity builds shipped public CRUD
# while CAPABILITIES.md claimed "auth + owner-scoped" on every entity.)
def caps_claim_exploit():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import eos, gen_models
    ents = [{"name": "Widget", "fields": [{"name": "id"}, {"name": "name", "type": "str"}]}]
    low = gen_models.effective_policies(ents, {"data_sensitivity": "low"})
    lab = eos.policy_label(low["Widget"])
    assert "PUBLIC" in lab and "owner-scoped" not in lab, \
        f"low-sensitivity label overstates security: {lab!r}"
    high = gen_models.effective_policies(
        ents + [{"name": "Note", "fields": [{"name": "id"}, {"name": "user_id"},
                                            {"name": "body", "type": "str"}]}],
        {"data_sensitivity": "high"})
    lab_h = eos.policy_label(high["Note"])
    assert "owner-scoped" in lab_h, f"high-sensitivity owner entity mislabeled: {lab_h!r}"
    # shorthand string fields (e.g. bikeshop's "fields": ["id", "email"]) must not crash
    short = gen_models.effective_policies(
        [{"name": "User", "fields": ["id", "email"]}], {"data_sensitivity": "low"})
    assert "PUBLIC" in eos.policy_label(short["User"])
check("CAPABILITIES.md security-claim accuracy", caps_claim_exploit)

# 9. Generated SPA must be CSP-compliant: the backend serves
# `Content-Security-Policy: default-src 'self'`, which blocks executable inline
# <script>/<style>/on* handlers. (2026-08-16: the inline single-file SPA rendered
# as a BLANK PAGE in every real browser; all HTTP-level checks passed anyway.)
def csp_frontend_exploit():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import re
    import gen_frontend as GF
    import gen_models as GM
    ent = {"name": "Item", "fields": ["id", {"name": "name", "type": "str"}]}
    fields = GM.norm_fields(ent)
    specs = GF.entity_specs([{"name": "Item", "fields": fields}],
                            {"Item": {"requires_auth": True}})
    files = GF.gen_frontend_files("test", "Test", specs)
    idx = files["index.html"]
    assert "styles.css" in idx and "app.js" in idx, "index must link external assets"
    for m in re.finditer(r"<script([^>]*)>", idx):
        attrs = m.group(1)
        assert 'src=' in attrs or 'type="application/json"' in attrs, \
            f"executable inline script in generated index.html: <script{attrs}>"
    assert "<style>" not in idx, "inline <style> blocked by CSP default-src 'self'"
    assert not re.search(r"\son(click|load|submit|change)=", idx), "inline event handler blocked by CSP"
    assert files["app.js"].strip() and files["styles.css"].strip()
check("Generated SPA renders under CSP", csp_frontend_exploit)

print(f"{'FINDING':<42} VERDICT")
print("-" * 70)
open_count = 0
for name, verdict, detail in results:
    print(f"{name:<42} {verdict}" + (f"  | {detail}" if detail else ""))
    if verdict != "CLOSED": open_count += 1
print("-" * 70)
print(f"all closed: {open_count == 0}")
sys.exit(1 if open_count else 0)
