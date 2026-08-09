#!/usr/bin/env python3
"""
eos.py — the Engineering Operating System core.

request -> pattern/domain/stage -> ENFORCE must_have/must_not -> resolve + materialize
        -> generate + WIRE models -> review -> cost -> validate (+ gate) -> BUILD_PLAN.md

    python tools/eos.py --request specs/examples/sobriety_journal.json --out ../app [--gate]
    python tools/eos.py --pattern saas_subscription_app --domain sobriety --stage growth --out ../app [--gate]

--gate: fail the build if any must_have is missing, any must_not is present, or a
high-sensitivity domain lacks its required safeguards. Without --gate, the same
issues are reported as warnings (advisory mode).
"""
from __future__ import annotations
try:
    import _bootstrap_path  # noqa: F401  (puts repo root on sys.path)
except ModuleNotFoundError:  # imported as tools.<mod>, not run as a script
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import _bootstrap_path  # noqa: F401
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)


def run(tool, *args):
    env = dict(os.environ, PYTHONPATH=ROOT)
    r = subprocess.run([PY, os.path.join(TOOLS, tool), *args],
                       capture_output=True, text=True, env=env, cwd=ROOT)
    return r.returncode, (r.stdout + r.stderr).strip()


def main(argv):
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    gate = "--gate" in argv
    if not out:
        print(__doc__); return 2

    if "--request" in argv:
        import plan_from_request as PR
        spec_path = os.path.join(ROOT, "_build_spec.json")
        PR.main([argv[argv.index("--request") + 1], "--out", spec_path])
        spec = json.load(open(spec_path, encoding="utf-8"))
        pattern, domain, stage = spec["pattern"], spec.get("domain"), spec.get("stage", "mvp")
        users = spec.get("expected_users")
        must_have, must_not = spec.get("must_have", []), spec.get("must_not", [])
    else:
        pattern = argv[argv.index("--pattern") + 1]
        domain = argv[argv.index("--domain") + 1] if "--domain" in argv else None
        stage = argv[argv.index("--stage") + 1] if "--stage" in argv else "mvp"
        users = int(argv[argv.index("--users") + 1]) if "--users" in argv else None
        must_have, must_not = [], []

    import resolve as R, validate_assembly as VA, review_plan as RV
    # build the enforced plan ONCE; everything downstream uses it
    pf_args = [pattern]
    if domain: pf_args += ["--domain", domain]
    if stage: pf_args += ["--stage", stage]
    if must_have: pf_args += ["--include", ",".join(must_have)]
    if must_not: pf_args += ["--exclude", ",".join(must_not)]
    plan = R.plan_from_args(pf_args)
    if not plan:
        print(f"unknown pattern: {pattern}"); return 1
    part_caps = plan["part_caps"]

    print(f"\n=== EOS: {pattern}" + (f"+{domain}" if domain else "")
          + f" @{stage} {'[GATE]' if gate else '[advisory]'} ===")

    # enforcement check FIRST
    gate_fails = VA.gate_check(part_caps, plan["domain"], must_have, must_not)
    must_have_ok = all(c in part_caps for c in must_have)
    must_not_ok = all(c not in part_caps for c in must_not)
    print(f"[enforce]    must_have honored: {must_have_ok}  must_not honored: {must_not_ok}")
    if gate and gate_fails:
        print("[GATE FAILED] build blocked:")
        for kind, msg in gate_fails:
            print(f"   - [{kind}] {msg}")
        print("  fix the plan (add safeguards / adjust request) or drop --gate for advisory mode.")
        return 3

    # The generated routes import security capabilities implied by the effective
    # per-entity policies (tier defaults + explicit overrides). Those parts MUST be
    # in the assembly or the generated app won't import. Use the SAME source of
    # truth as generation (gen_models.effective_policies) so the two never drift.
    policy_caps: set[str] = set()
    dobj = plan.get("domain")
    if dobj:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import gen_models as GM
        ents = [{"name": e["name"], "fields": GM.norm_fields(e)} for e in dobj.get("entities", [])]
        eps = GM.effective_policies(ents, dobj)
        policy_caps = GM.implied_capabilities(eps)
        # role-managed entities (route_policies[...].write_role) need the roles store
        if any((rp or {}).get("write_role") for rp in (dobj.get("route_policies") or {}).values()):
            policy_caps |= {"roles", "permissions"}
        if dobj.get("retention_days"):
            policy_caps.add("retention_policy")   # generated app imports it at runtime
        # PQC posture: high-sensitivity domains face harvest-now-decrypt-later, so
        # every such build ships the hybrid post-quantum implementations by default
        # (crypto agility + envelope key-wrapping + audit-witness signing). They are
        # included regardless of whether the entity policies happen to reference them,
        # so the protection is present in the artifact, not bolted on later.
        if dobj.get("data_sensitivity") in ("high", "regulated"):
            policy_caps |= {"crypto_agility", "pq_envelope", "pq_signing"}
        # every domain app ships an auth surface + a generated frontend, so a user
        # can register, sign in, and operate the generated REST API end-to-end —
        # the backend and UI are composed from the same entities/contract.
        if dobj.get("entities"):
            policy_caps |= {"auth_routes", "jwt_manager", "users", "session_manager"}
    include_caps = list(dict.fromkeys(list(must_have) + sorted(policy_caps)))
    if policy_caps:
        print(f"[policy-deps] generated routes require: {', '.join(sorted(policy_caps))} (force-included)")

    # materialize honoring include/exclude
    mat = [pattern] + (["--domain", domain] if domain else []) + (["--stage", stage] if stage else [])
    if include_caps: mat += ["--include", ",".join(include_caps)]
    if must_not: mat += ["--exclude", ",".join(must_not)]
    mat += ["--out", out]
    rc, o = run("resolve.py", *mat)
    print("[resolve]    " + (o.splitlines()[-1] if o else "done"))

    # bundle runtime infrastructure (not a catalog part, but required for main.py to boot)
    import shutil
    rt_src = os.path.join(ROOT, "scrapyard", "runtime")
    rt_dst = os.path.join(out, "scrapyard", "runtime")
    if os.path.isdir(rt_src):
        shutil.copytree(rt_src, rt_dst, dirs_exist_ok=True)
        print("[runtime]    bundled scrapyard/runtime (settings, database, lifespan, startup)")

    # generate + wire models
    if domain:
        rc, o = run("gen_models.py", domain, os.path.join(out, "scrapyard", "models"), "--wire")
        print("[models]     " + (o.splitlines()[-1] if o else "done"))
        # real app entrypoint: load settings, init DB engine, create tables in dev,
        # install security headers, mount generated routers. Production uses migrations.
        safe_app = bool(plan["domain"]) and plan["domain"].get("data_sensitivity") in ("high", "regulated")
        # the generated app mounts auth + serves a frontend, so it needs the
        # library auth-principal ('users') and session tables created at boot.
        sec_caps = sorted((policy_caps & {"audit_logs", "roles"}) | {"users", "session_manager"})

        # generate the frontend from the SAME domain entities/contract as the backend
        run("gen_frontend.py", domain, os.path.join(out, "frontend"))
        print("[frontend]   generated SPA -> frontend/index.html (served at /app)")

        # retention enforcement: if the domain declares retention_days, generate a
        # retention module and run it on startup so declared policy is ACTUALLY
        # executed at runtime (not just documented).
        retention_rules = (plan["domain"] or {}).get("retention_days") or {}
        if retention_rules:
            ret_src = (
                '"""Generated retention wiring — auto-expire data per the domain\'s '
                'retention_days. Idempotent: only deletes rows past their max age."""\n'
                "from scrapyard.compliance.retention_policy import RetentionPolicy\n"
                "from scrapyard.models import models as _M\n\n"
                f"RETENTION_RULES = {retention_rules!r}\n\n"
                "def _models_by_table():\n"
                "    out = {}\n"
                "    for _n in dir(_M):\n"
                "        obj = getattr(_M, _n)\n"
                "        tbl = getattr(obj, '__tablename__', None)\n"
                "        if tbl:\n"
                "            out[tbl] = obj\n"
                "    return out\n\n"
                "def run_retention(db) -> dict:\n"
                "    policy = RetentionPolicy(RETENTION_RULES)\n"
                "    by_table = _models_by_table()\n"
                "    purged = {}\n"
                "    for table, days in RETENTION_RULES.items():\n"
                "        model = by_table.get(table)\n"
                "        if model is None:\n"
                "            continue\n"
                "        purged[table] = policy.purge(db, model, days)\n"
                "    db.commit()\n"
                "    return purged\n"
            )
            open(os.path.join(out, "scrapyard", "models", "retention.py"), "w", encoding="utf-8").write(ret_src)

        hooks_block = ""
        bootstrap_hooks = ""
        if retention_rules:
            hooks_block = (
                "from scrapyard.runtime.lifespan import Hooks\n"
                "from scrapyard.database.db_session import session_scope\n"
                "from scrapyard.models.retention import run_retention\n"
                "_hooks = Hooks()\n\n"
                "@_hooks.on_startup\n"
                "def _retention_sweep():\n"
                "    with session_scope() as _db:\n"
                "        run_retention(_db)\n\n"
            )
            bootstrap_hooks = "    hooks=_hooks,\n"
        wiring = (
            '"""Generated application entrypoint. Boots with: uvicorn main:app"""\n'
            "import os\n"
            "from scrapyard.runtime.startup import bootstrap\n"
            "from scrapyard.models.models import Base\n"
            "from scrapyard.models.routes import router as models_router\n"
            "from scrapyard.database.db_session import get_db\n"
            "from scrapyard.identity.auth_routes import build_auth_router\n"
            "from fastapi.staticfiles import StaticFiles\n\n"
            + hooks_block +
            "app = bootstrap(\n"
            "    routers=[models_router, build_auth_router(get_db)],\n"
            "    models_base=Base,\n"
            f"    require_encryption={safe_app},\n"
            f"    security_caps={sec_caps!r},\n"
            + bootstrap_hooks +
            ")\n\n"
            "# serve the generated single-page frontend at /app (talks to the API above)\n"
            "_fe = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend')\n"
            "if os.path.isdir(_fe):\n"
            "    app.mount('/app', StaticFiles(directory=_fe, html=True), name='frontend')\n\n"
            "# run:  DATABASE_URL=... "
            + ("PQ_FIELD_PUBLIC=... PQ_FIELD_SECRET=... " if safe_app else "")
            + "uvicorn main:app --reload   ->  UI at /app\n"
        )
        open(os.path.join(out, "main.py"), "w", encoding="utf-8").write(wiring)
        # .env.example — document every env var the app reads, so a fresh clone can boot.
        _env_lines = [
            "# Generated environment template — copy to .env and fill in.",
            "APP_ENV=development            # development | production",
            "DATABASE_URL=sqlite:///./app.db  # e.g. postgresql+psycopg2://user:pass@host/db in prod",
            "SECRET_KEY=change-me-to-a-long-random-string",
        ]
        if safe_app:
            _env_lines += [
                "# Hybrid post-quantum field-encryption keys (required for this sensitive domain).",
                "# Generate with: python -c \"from scrapyard.security.pq_field_encryption import generate_recipient_hex as g; pk,sk=g(); print('PQ_FIELD_PUBLIC='+pk); print('PQ_FIELD_SECRET='+sk)\"",
                "PQ_FIELD_PUBLIC=",
                "PQ_FIELD_SECRET=",
            ]
        open(os.path.join(out, ".env.example"), "w", encoding="utf-8").write("\n".join(_env_lines) + "\n")
        print("[wire]       wrote main.py (runtime.bootstrap: settings+db+lifecycle+routers+headers"
              + (" + encryption guard" if safe_app else "")
              + " + auth + frontend"
              + (" + retention sweep)" if retention_rules else ")"))

        # Import-closure: the capability graph only knows declared edges, so function-local
        # imports (e.g. auth_routes -> security.password_policy) get left behind. Run the
        # SAME closure expansion assemble uses, so EOS apps are import-complete too.
        from dependency_closure import expand_dependency_closure
        cl = expand_dependency_closure(out)
        if cl["added"]:
            print(f"[closure]    +{len(cl['added'])} module(s) the graph missed: {', '.join(cl['added'])}")
        if cl["unresolved"]:
            print(f"[closure]    WARNING unresolved imports: {', '.join(cl['unresolved'])}")

    # honest per-build inventory: entities, FK relationships, workflows, per-entity
    # security, and what is explicitly NOT enforced (sourced from the hardening registry).
    if domain:
        try:
            from gen_build_report import write_report, write_legal_docs
            rep = write_report(domain, out)
            write_legal_docs(domain, out)
            rs = rep["summary"]
            print(f"[report]     {rs['entities']} entities · {rs['relationships_with_foreign_keys']} FK relationship(s) · "
                  f"{rs['workflows']} workflow(s) -> BUILD_REPORT.md + build_report.json")
            print("[legal]      wrote PRIVACY_POLICY.md + TERMS_OF_SERVICE.md (templates — require legal review)")
        except Exception as _re:
            print(f"[report]     skipped ({_re!r})")

    # reasoning docs from the SAME enforced plan
    fr = RV.write_docs(plan, out, users)
    print(f"[review]     validation pass + fitness: {fr['verdict']}")
    rc, o = run("cost_scale.py", *(mat[:-2]), "--md", out)
    print("[cost]       " + (o.splitlines()[-1] if o else "done"))

    # operational reasoning — failure cascade analysis through the dependency graph
    rc_o, o_o = run("ops_reason.py", "report", *(mat[:-2]))
    open(os.path.join(out, "OPERATIONS_REASONING.md"), "w", encoding="utf-8").write(
        "# Operational reasoning\n\n```\n" + o_o + "\n```\n")
    ext_line = next((l for l in o_o.splitlines() if l.startswith("External dependencies")), "")
    print("[ops-reason] " + (ext_line or "wrote OPERATIONS_REASONING.md"))

    # behavior verification — prove implemented capabilities work, not just boot
    vargs = [pattern] + (["--domain", domain] if domain else []) + (["--stage", stage] if stage else [])
    if must_have: vargs += ["--include", ",".join(must_have)]
    if must_not: vargs += ["--exclude", ",".join(must_not)]
    rc_v, o_v = run("verify_build.py", *vargs)
    vline = next((l for l in o_v.splitlines() if l.strip().startswith("=>")), "=> (no result)")
    verify_ok = rc_v == 0
    print("[verify]     " + vline.strip())
    if gate and not verify_ok:
        print("[GATE FAILED] behavior verification failed — build blocked.")
        return 3

    # per-entity probe metadata: an auditable record of each entity's CRUD (+ workflow)
    # probe over HTTP — verification you can read entity-by-entity, shipped with the app.
    rc_pm, o_pm = run("gen_probe_metadata.py", out)
    pmline = next((l for l in o_pm.splitlines() if l.strip().startswith("[metadata]")), "")
    print(pmline.strip() or "[metadata]   wrote PROBE_METADATA.md")

    # workflow verification — prove end-to-end business sequences
    rc_w, o_w = run("verify_workflow.py", "run-all")
    wf_verified = o_w.count("WORKFLOW VERIFIED")
    wf_failed = o_w.count("WORKFLOW FAILED")
    wf_blocked = o_w.count("=> BLOCKED")
    print(f"[workflows]  {wf_verified} verified, {wf_blocked} blocked (stubs), {wf_failed} failed")
    if gate and wf_failed:
        print("[GATE FAILED] a business workflow failed — build blocked.")
        return 3

    # active lessons: applicable lessons whose mitigation is absent
    import lessons as LZ
    rel = LZ.relevant_to(part_caps, plan["pattern"].get("extends_chain", []),
                         plan["domain"].get("extends_chain", []) if plan["domain"] else [], stage)
    unmit = [(L["id"], L["title"], L["mitigation"]) for L in rel
             if L.get("mitigation") and L["mitigation"] not in part_caps]
    # plan confidence
    import confidence_report as CR
    cs = CR.summarize(list(part_caps))

    # validation verdict
    findings = VA.run_rules(part_caps, stage=stage, res=plan["res"],
                            graph_stage_of=R.load_stages()["stage_of"])
    worst = "PASS"
    for _, s, _ in findings:
        if s == "FAIL": worst = "FAIL"
        elif s == "WARN" and worst != "FAIL": worst = "WARN"

    # CAPABILITIES.md — honest: what runs, what's required for prod, what's a
    # local-only fallback. The fallback section mirrors runtime/fallbacks.py.
    try:
        import gen_models as _GM
        caps_sorted = sorted(part_caps)
        ents = (plan["domain"] or {}).get("entities", []) if domain else []
        routes = ["`GET /healthz`, `GET /livez` — health/liveness"]
        if domain:
            routes.append("`POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`")
            for e in ents:
                pl = _GM._plural(e["name"])
                routes.append(f"`GET|POST /{pl}`, `GET|PUT|DELETE /{pl}/{{id}}` — {e['name']} CRUD (auth + owner-scoped)")
            routes.append("`GET /app/` — generated single-page frontend")
        ENV = []
        ENV.append(("DATABASE_URL", "required (non-dev)", "Postgres/MySQL URL; dev falls back to local sqlite"))
        if "pq_field_encryption" in part_caps:
            ENV.append(("PQ_FIELD_PUBLIC / PQ_FIELD_SECRET", "required", "hybrid PQ recipient keypair for at-rest field encryption (rotatable; or citadel custody)"))
        if part_caps & {"pq_envelope", "pq_signing", "crypto_agility"}:
            ENV.append(("SCRAPYARD_CRYPTO_BACKEND=citadel", "required in prod", "reference-impl crypto is refused in production; point at the citadel signer/keystore"))
        if "audit_logs" in part_caps:
            ENV.append(("AUDIT_WITNESS_PUBLIC / AUDIT_WITNESS_SECRET", "recommended", "stable audit witness key for cross-restart tamper-evidence"))
        if part_caps & {"stripe_checkout", "stripe_webhooks", "subscriptions"}:
            ENV.append(("STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET", "required for billing", "real Stripe credentials"))
        if "email" in part_caps:
            ENV.append(("SMTP_HOST / SMTP_URL / EMAIL_PROVIDER", "required in prod", "without it, email logs to console instead of sending"))
        if "db_queue" in part_caps:
            ENV.append(("JOBS_BACKEND=db", "required in prod", "use the durable DB queue; the in-memory queue is refused in production"))
        cap = [
            f"# Capabilities — {pattern}" + (f" + {domain}" if domain else ""),
            "_Generated honestly from the assembled plan. Lists what actually runs, "
            "what production requires, and which local-only fallbacks ship by default._\n",
            f"## Included parts ({len(caps_sorted)})", "",
            ", ".join(f"`{c}`" for c in caps_sorted), "",
            "## Runnable endpoints", "", *[f"- {r}" for r in routes], "",
            "## Required configuration", "",
            "| Variable | When | Notes |", "|---|---|---|",
            *[f"| `{k}` | {when} | {note} |" for k, when, note in ENV], "",
            "## Local-only fallbacks (refused in production)", "",
            "These ship active by default for dev/test; `bootstrap()` refuses to start "
            "with `APP_ENV=production` while any are live, so they can never run silently in prod:", "",
            "- **security.local_crypto_backend** — reference-impl ML-KEM/ML-DSA. Disable: `SCRAPYARD_CRYPTO_BACKEND=citadel`.",
            "- **communication.email_console** — email logged, not sent. Disable: configure `SMTP_HOST`/`SMTP_URL`/`EMAIL_PROVIDER`.",
            "- **ai.offline_provider** — AI calls use an offline stub. Disable: set `SCRAPYARD_LLM_PROVIDER` + provider key.",
            "",
            "## Local-only (warned, not blocked)", "",
            "- **audit.ephemeral_witness_key** — process-generated witness key (not durable across restarts). Set `AUDIT_WITNESS_PUBLIC/SECRET` for durable evidence.",
            "",
            "## Honest limits", "",
            "- Generated CRUD is generic (no product-specific business logic yet).",
            "- Tables auto-create in dev; use migrations for production schema management.",
            "- Reference-impl PQ crypto is not FIPS/CMVP-validated — citadel or a validated backend closes that.",
        ]
        open(os.path.join(out, "CAPABILITIES.md"), "w", encoding="utf-8").write("\n".join(cap))
        print("[capabilities] wrote CAPABILITIES.md (endpoints + required config + honest fallbacks)")
    except Exception as _e:
        print(f"[capabilities] skipped ({type(_e).__name__})")

    # Run the shared generated-app contract only after every artifact it checks
    # has been written. Previously CAPABILITIES.md was produced after this gate,
    # creating a false failure that advisory builds silently returned as rc=0.
    rc_g, o_g = run("verify_generated_app.py", out)
    gline = next((l for l in o_g.splitlines()
                  if l.startswith("PASS") or l.startswith("FAILED")), "")
    print("[runnable]   " + (gline or "verify_generated_app done"))
    if rc_g != 0:
        print("[GATE FAILED] generated app failed the unified runnable-app verifier.")
        return 3

    # BUILD_PLAN.md — honest about enforcement + wiring
    docs = ["START.md","CAPABILITIES.md","DOMAIN.md","COMPOSITIONS.md","LESSONS.md","CONFIDENCE.md","OPERATIONS.md",
            "OPERATIONS_REASONING.md","FITNESS.md","SIMULATION.md","DECISIONS.md","RISK_REGISTER.md","COST.md","main.py"]
    present_docs = [d for d in docs if os.path.exists(os.path.join(out, d))]
    pat, dom = plan["pattern"], plan["domain"]
    L = [f"# Build plan — {pattern}" + (f" + {domain}" if domain else ""),
         f"Stage **{stage}**" + (f", ~{users} users" if users else "")
         + f", mode **{'GATE' if gate else 'advisory'}**.\n",
         f"- Pattern inheritance: {' <- '.join(pat.get('extends_chain', [pattern]))}",
         (f"- Domain inheritance: {' <- '.join(dom.get('extends_chain', [domain]))}" if dom else ""),
         f"- Parts resolved: {len(part_caps)}",
         "\n## Requirements enforcement",
         f"- must_have: {must_have or 'none'} — **{'HONORED' if must_have_ok else 'NOT HONORED'}**",
         f"- must_not: {must_not or 'none'} — **{'HONORED' if must_not_ok else 'NOT HONORED'}**",
         (f"- Gate findings: {len(gate_fails)}" if gate_fails else "- Gate findings: none"),
         *[f"  - [{k}] {m}" for k, m in gate_fails],
         "\n## Verdicts",
         f"- Validation: **{worst}**",
         f"- Fitness: **{fr['verdict']}**" + (f" — {fr['findings'][0][1]}" if fr["findings"] else ""),
         f"- Behavior verification: {vline.strip()[3:]}",
         f"- Workflow verification: **{wf_verified} verified**, {wf_blocked} blocked (stub-dependent), {wf_failed} failed",
         f"- Plan confidence: avg **{cs['avg']}** ("
         + ", ".join(f"{k} {v}" for k, v in sorted(cs['distribution'].items())) + ")",
         "\n## Active lessons (mitigations missing from this plan)",
         *( [f"- ⚠ {lid}: {title} — add `{mit}`" for lid, title, mit in unmit] or ["- none — all applicable lesson mitigations present"]),
         "\n## Generated code wiring",
         ("- Generated routers mounted via `main.py` (create_app(routers=[...]))."
          if domain else "- No domain models generated."),
         "\n## Dossier", *[f"- [{d}]({d})" for d in present_docs],
         "\n## Next",
         "1. `pip install -r requirements.txt`",
         "2. All parts are implemented; see CONFIDENCE.md (contract-tested vs. needs hardening) and CAPABILITIES.md (endpoints, required config, local-only fallbacks).",
         "3. Address FITNESS.md / SIMULATION.md findings before launch.",
         "4. Configure secrets from the validation output."]
    open(os.path.join(out, "BUILD_PLAN.md"), "w", encoding="utf-8").write("\n".join(x for x in L if x))

    print(f"\n=== DONE -> {out} ===")
    print(f"  validation={worst}  fitness={fr['verdict']}  impl_behavior_checks={'passed' if verify_ok else 'FAILED'}  "
          f"confidence={cs['avg']}  parts={len(part_caps)}  "
          f"must_have={'ok' if must_have_ok else 'MISSING'}  must_not={'ok' if must_not_ok else 'VIOLATED'}")
    if unmit:
        print(f"  active lessons flag {len(unmit)} missing mitigation(s): "
              + ", ".join(m for _, _, m in unmit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
