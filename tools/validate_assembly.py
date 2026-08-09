#!/usr/bin/env python3
"""
validate_assembly.py — can this assembly actually build?

Knowing how to assemble is not the same as knowing the assembly is sound. This
runs a battery of checks over a plan (resolved from a pattern) or an already-
materialized app directory, and reports PASS / WARN / FAIL per rule.

    python tools/validate_assembly.py <pattern> [--domain d] [--stage s]
    python tools/validate_assembly.py --dir <assembled_app_dir>

Rules:
  R1 dependency-closure   every required capability resolves (no UNRESOLVED)
  R2 implied-parts        parts that need siblings have them (e.g. feature_gates
                          -> entitlement_gate + subscription_status)
  R3 http-wiring          route/webhook parts require app_factory present
  R4 persistence          ORM-backed parts require db_session + base_model
  R5 secrets              aggregate the env/secrets the plan will need (WARN)
  R6 conflicts            no two parts that are alternatives for one capability
  R7 stage-coherence      nothing pulled transitively above the requested stage
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
CAT = os.path.join(ROOT, "catalog.json")
ALT = os.path.join(ROOT, "alternatives")
LIFE = os.path.join(ROOT, "lifecycle", "stages.json")

# part-name -> parts it cannot work without (checked at the part level)
IMPLIES = {
    "feature_gates": ["entitlement_gate", "subscription_status"],
    "entitlement_gate": ["subscription_status"],
    "subscription_status": ["subscriptions"],
    "stripe_webhooks": ["subscriptions"],
    "stripe_checkout": ["subscriptions"],
    "auth_routes": ["users", "password_hashing", "jwt_manager", "session_manager"],
    "rag": ["embeddings", "vector_store", "llm_client"],
    "password_reset": ["users", "email"],
    "email_verification": ["users", "email"],
    "impersonation": ["users", "session_manager", "audit_logs"],
}
HTTP_PARTS = {"stripe_checkout", "stripe_webhooks", "invoice_portal",
              "oauth_google", "webhooks_inbound"}  # plus anything ending _routes
ORM_PARTS = {"users", "subscriptions", "audit_logs", "invoices", "roles"}
# part present -> at least one of these observability/safety parts should be present
OBSERVABILITY_REQ = {
    "stripe_webhooks": ["audit_logs", "structured_logging"],
    "subscriptions": ["audit_logs", "structured_logging"],
    "queues": ["dead_letter", "retries"],
    "llm_client": ["token_cost_logging"],
    "rag": ["token_cost_logging"],
    "auth_routes": ["account_lockout", "rate_limiting"],
    "user_management": ["audit_logs"],
    "impersonation": ["audit_logs"],
}
SECRETS = {
    "jwt_manager": ["JWT_SECRET_KEY"],
    "stripe_checkout": ["STRIPE_API_KEY"], "stripe_webhooks": ["STRIPE_WEBHOOK_SECRET"],
    "subscriptions": ["STRIPE_API_KEY"],
    "oauth_google": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
    "llm_client": ["LLM_API_KEY"], "embeddings": ["LLM_API_KEY"],
    "email": ["SMTP_URL"], "sms": ["SMS_API_KEY"],
    "db_session": ["DATABASE_URL"], "vector_store": ["VECTOR_DB_URL"],
    "storage_adapters": ["STORAGE_BUCKET", "STORAGE_KEY"],
}


def catalog_by_import() -> dict:
    cat = json.load(open(CAT, encoding="utf-8"))
    out = {}
    for parts in cat["layers"].values():
        for p in parts:
            out[p["import_path"]] = p
    return out


def parts_from_dir(d: str) -> set[str]:
    """Catalog part short-names present in an assembled app dir.

    Only counts files that are actually catalog parts (carry a PART-META-JSON
    metadata); generated folders like scrapyard/models are correctly ignored."""
    names = set()
    base = os.path.join(d, "scrapyard")
    if not os.path.isdir(base):
        return names
    for layer in os.listdir(base):
        ldir = os.path.join(base, layer)
        if not os.path.isdir(ldir):
            continue
        for fn in os.listdir(ldir):
            if not fn.endswith(".py") or fn == "__init__.py":
                continue
            try:
                head = open(os.path.join(ldir, fn), encoding="utf-8").read(2000)
            except Exception:
                continue
            if "PART-META-JSON" in head:   # real catalog part, not generated code
                names.add(fn[:-3])
    return names


def exclusive_pairs() -> list[set[str]]:
    """Explicitly mutually-exclusive part sets. Alternatives are *choices*, not
    conflicts — most coexist (a real app uses sessions AND jwt). Only parts that
    genuinely cannot run together belong here. The current yard has none; the
    mechanism exists for when a part with a hard exclusivity is added."""
    return []


SENSITIVE_REQUIRED = ["account_deletion", "data_export", "field_encryption",
                      "retention_policy", "privacy_policy_hooks"]
SENSITIVE_AUDIT = ["audit_logs", "structured_logging"]


def _impl_status():
    import json as _json
    cf = os.path.join(ROOT, "confidence", "confidence.json")
    if not os.path.exists(cf):
        return {}
    return _json.load(open(cf, encoding="utf-8"))["capabilities"]


def gate_check(part_caps: set[str], domain: dict | None,
               must_have=None, must_not=None) -> list[tuple]:
    """Hard requirements for a gated build. Returns FAIL findings (empty = pass).

    For high-sensitivity domains, a required safeguard must be not just PRESENT in
    the plan but IMPLEMENTED (status proven/core) — a stub safeguard provides no
    real protection, so accepting it would be the gate lying."""
    fails = []
    conf = _impl_status()

    def implemented(cap):
        st = conf.get(cap, conf.get(cap.split(".")[-1], {})).get("status")
        return st in ("proven", "stable")  # stable = implemented; proven = implemented + tested

    for c in (must_have or []):
        if c not in part_caps:
            fails.append(("must_have", f"required capability missing: {c}"))
    for c in (must_not or []):
        if c in part_caps:
            fails.append(("must_not", f"forbidden capability present: {c}"))
    if domain and domain.get("data_sensitivity") in ("high", "regulated"):
        for c in SENSITIVE_REQUIRED:
            if c not in part_caps:
                fails.append(("sensitive", f"sensitive domain requires {c}"))
            elif not implemented(c):
                fails.append(("sensitive-unimplemented",
                              f"safeguard {c} is present but UNIMPLEMENTED (stub) — "
                              f"provides no real protection"))
        audit = [a for a in SENSITIVE_AUDIT if a in part_caps]
        if not audit:
            fails.append(("sensitive", f"sensitive domain requires one of {SENSITIVE_AUDIT}"))
        elif not any(implemented(a) for a in audit):
            fails.append(("sensitive-unimplemented",
                          f"audit safeguard present ({', '.join(audit)}) but UNIMPLEMENTED (stub)"))
        # Encryption coverage: every text field must be explicitly classified as
        # encrypted or exempt. An unclassified text field is silent plaintext PII.
        try:
            import gen_models as _GM
            ents = [{"name": e["name"], "fields": _GM.norm_fields(e)}
                    for e in domain.get("entities", [])]
            for ename, flds in _GM.encryption_coverage_fails(ents, domain):
                fails.append(("sensitive-plaintext",
                              f"{ename} has unclassified text field(s) {flds} — declare them "
                              f"encrypted (sensitive_fields/route_policies) or exempt (exempt_fields)"))
        except Exception as e:
            fails.append(("sensitive-plaintext",
                          f"could not verify encryption coverage: {type(e).__name__}: {e}"))
    return fails


def run_rules(part_names: set[str], *, stage: str | None,
              res: dict | None, graph_stage_of: dict | None) -> list[tuple]:
    findings = []  # (rule, status, detail)

    # R1 dependency-closure (only meaningful when we resolved a plan)
    if res is not None:
        if res["unknown"]:
            findings.append(("R1 dependency-closure", "FAIL",
                             "unresolved: " + ", ".join(res["unknown"])))
        else:
            findings.append(("R1 dependency-closure", "PASS", "all capabilities resolve"))

    # R2 implied-parts
    missing_impl = []
    for p in part_names:
        for need in IMPLIES.get(p, []):
            if need not in part_names:
                missing_impl.append(f"{p} needs {need}")
    findings.append(("R2 implied-parts", "FAIL" if missing_impl else "PASS",
                     "; ".join(missing_impl) if missing_impl else "all implied parts present"))

    # R3 http-wiring
    http = [p for p in part_names if p.endswith("_routes") or p in HTTP_PARTS]
    if http and "app_factory" not in part_names:
        findings.append(("R3 http-wiring", "FAIL",
                         f"HTTP parts present ({', '.join(sorted(http))}) but no app_factory"))
    elif http:
        findings.append(("R3 http-wiring", "PASS", f"{len(http)} HTTP parts, app_factory present"))
    else:
        findings.append(("R3 http-wiring", "PASS", "no HTTP-exposing parts"))

    # R4 persistence
    orm = [p for p in part_names if p in ORM_PARTS or p in ("repository", "soft_delete", "timestamps")]
    if orm and ("db_session" not in part_names or "base_model" not in part_names):
        miss = [x for x in ("db_session", "base_model") if x not in part_names]
        findings.append(("R4 persistence", "FAIL",
                         f"ORM parts present but missing {', '.join(miss)}"))
    elif orm:
        findings.append(("R4 persistence", "PASS", "db_session + base_model present"))
    else:
        findings.append(("R4 persistence", "PASS", "no ORM-backed parts"))

    # R5 secrets (advisory)
    needed = sorted({s for p in part_names for s in SECRETS.get(p, [])})
    findings.append(("R5 secrets", "WARN" if needed else "PASS",
                     ("must be configured: " + ", ".join(needed)) if needed else "none required"))

    # R6 conflicts
    conflicts = []
    for grp in exclusive_pairs():
        present = grp & part_names
        if len(present) > 1:
            conflicts.append(" vs ".join(sorted(present)))
    findings.append(("R6 conflicts", "FAIL" if conflicts else "PASS",
                     "; ".join(conflicts) if conflicts else "no conflicting implementations"))

    # R7 stage-coherence
    if stage and res is not None and graph_stage_of:
        order = ["mvp", "growth", "scale", "enterprise"]
        limit = order.index(stage)
        leaks = []
        for sub in res["subsystems"]:
            rank = order.index(graph_stage_of.get(sub, "mvp"))
            if rank > limit:
                leaks.append(f"{sub}({graph_stage_of[sub]})")
        findings.append(("R7 stage-coherence", "WARN" if leaks else "PASS",
                         ("pulled above stage: " + ", ".join(leaks)) if leaks
                         else f"nothing above {stage}"))
    # R8 observability-requirements
    obs_missing = []
    for p in part_names:
        req = OBSERVABILITY_REQ.get(p)
        if req and not any(r in part_names for r in req):
            obs_missing.append(f"{p} needs one of [{', '.join(req)}]")
    findings.append(("R8 observability", "WARN" if obs_missing else "PASS",
                     "; ".join(obs_missing) if obs_missing else "monitoring/safety parts present"))
    return findings


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    res = None
    stage = None
    graph_stage_of = None
    if argv[0] == "--dir":
        app_dir = argv[argv.index("--dir") + 1]
        part_names = parts_from_dir(app_dir)
        if not part_names:
            print(f"no parts found under {app_dir}/scrapyard")
            return 1
        header = f"validating assembled dir: {app_dir} ({len(part_names)} parts)"
    else:
        import resolve as R
        plan = R.plan_from_args(argv)
        if not plan:
            print(f"unknown pattern: {argv[0]}")
            return 1
        stage = plan["stage"]
        res = plan["res"]
        if stage:
            graph_stage_of = R.load_stages()["stage_of"]
        part_names = plan["part_caps"]
        header = (f"validating plan: {plan['pattern_name']}"
                  + (f"+{plan['domain_name']}" if plan["domain_name"] else "")
                  + (f" @{stage}" if stage else "")
                  + (f" +{plan['include']}" if plan["include"] else "")
                  + (f" -{plan['exclude']}" if plan["exclude"] else "")
                  + f" ({len(part_names)} parts)")

    findings = run_rules(part_names, stage=stage, res=res, graph_stage_of=graph_stage_of)
    print(header)
    worst = "PASS"
    for rule, status, detail in findings:
        print(f"  [{status:4}] {rule:22} {detail}")
        if status == "FAIL":
            worst = "FAIL"
        elif status == "WARN" and worst != "FAIL":
            worst = "WARN"
    print(f"  => {worst}")
    return 1 if worst == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
