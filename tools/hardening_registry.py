"""hardening_registry.py — classify every capability beyond "core".

Four cumulative levels, each COMPUTED or explicitly evidenced (never assumed):
  implemented — present as core in the catalog
  verified    — has a passing behavior contract (tools/verify_build.py all)
  hardened    — edge/failure/security concerns addressed; defaults FALSE and is
                only true where real evidence is registered (HARDENED set below)
  operational — failure modes / dependencies declared in operations/

Honesty rule: "hardened" is the level most capabilities have NOT reached. For
security-critical capabilities we record the specific gaps rather than pretend.

Writes hardening_registry.json and HARDENING.md.
Usage: python tools/hardening_registry.py [--write]
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Capabilities with REAL hardening evidence today. Kept deliberately small and
# honest — empty until a capability has rotation/recovery/tamper/edge coverage.
HARDENED: dict[str, str] = {
    # e.g. "field_encryption": "key rotation + versioned keys + recovery tested"
    # (none yet — see KNOWN_GAPS)
}

# Explicit, documented hardening gaps for the security-critical subsystems.
KNOWN_GAPS = {
    "field_encryption": ["legacy Fernet at-rest part; superseded for generated apps by pq_field_encryption",
                         "Fernet path itself still lacks key rotation / versioning"],
    "pq_field_encryption": ["hybrid PQ at-rest with key ROTATION + self-describing suite (versioning) — IMPLEMENTED & proven",
                            "still pending: row-level AAD (binds to table.column, not per-row); per-value KEM is heavier than a shared DEK; key custody is env-based unless citadel; local ML-KEM not constant-time/audited"],
    "audit_logs": ["tamper detection ADDED (hash chain + hybrid-PQ witness, verify_chain proven)",
                   "still pending: DB-enforced append-only (GRANTs/triggers)",
                   "witness-key rotation / durable custody (set AUDIT_WITNESS_* or citadel)",
                   "no archival/retention backend"],
    "account_deletion": ["blunt cascade", "no legal-hold / anonymization / soft-delete modes"],
    "domain_enforcement": ["service-layer domain rules beyond CRUD — an entity may declare reference_rules (a relationship field must reference an existing row in an eligible status), no_overlap (date-range conflict detection on a scoped field), cross-entity transition guards (a related row must be in an allowed status), and transition EFFECTS (set_related mutates a related row; create auto-creates child records). Generated services raise DomainRuleError/WorkflowError -> clean 409. The full tool-library sequence (reserve -> checkout drives tool state -> damaged return auto-creates incident+maintenance and locks the tool -> complete maintenance frees it -> reserve again) is proven over HTTP + by the domain_enforcement and transition_effects contracts — IMPLEMENTED & proven",
                            "effects may now be GUARDED (guarded: true) — set_related then routes through the target entity's own transition() so its transition table + guards apply (an illegal/blocked routed transition raises WorkflowError and nothing mutates; proven by the guarded_effects contract). Still pending: a non-guarded effect still sets the field directly (the default, for fields with no state machine); effect-created child records bypass the child's reference_rules. Time-based transitions ARE now generated: a state_machine may declare time_transitions and the generator emits a sweep() + POST /<entity>/sweep that advances rows whose deadline field has passed (through transition(), so guards/effects apply) — driven by an external scheduler (cron/worker); proven by the time_transitions contract + HTTP e2e"],
    "transition_effects": ["side-effecting transitions — covered under domain_enforcement; set_related + create effects proven by the transition_effects contract"],
    "probe_metadata": ["per-entity probe metadata — gen_probe_metadata boots the app, authenticates (elevating to admin so role-gated writes are exercised), runs each resource entity's create/read/update/delete (+ a workflow transition-guard check) over HTTP, and writes PROBE_METADATA.md + probe_metadata.json. Run by the eos pipeline; locked by the probe_metadata contract — IMPLEMENTED & proven",
                        "still pending: the sampler fills only required fields with type-default values, so entities with cross-field validation or required server-validated formats may show a create FAIL that is a probe limitation, not an app defect; informational (not a build gate)"],
    "unified_verifier": ["one runnable-app verifier for both generation paths — verify_generated_app asserts ONE shared file-tree contract uniformly on BOTH flavors (top-level main:app, importable scrapyard/ library package, requirements.txt, .env.example, CAPABILITIES.md metadata, a feature/domain code package, and >=1 feature route), boots main:app in an isolated subprocess, and checks boot/health/isolation. Each path adds exactly one path-specific extra (assemble: /capabilities JSON; eos: BUILD_REPORT.md). Run by build_matrix (assemble) and the eos pipeline (eos); locked by the unified_verifier contract which scaffolds BOTH flavors and asserts the same contract — IMPLEMENTED & proven",
                          "by design the two paths emit different CONTENT (a template app vs a domain app: feature code under scrapyard_app/ vs domain models under scrapyard/models/), so the trees are not byte-identical — the unification is the verifier-enforced shared contract, not identical layouts; deep domain checks (secure/fullstack adversarial probes) remain eos-only via verify_runtime"],
    "roles": ["role-based authorization — persistent user_roles store + principal/permission expansion; an entity may declare route_policies[...].write_role so create/update/delete require that role (or a superuser 'owner' role) while reads stay auth-only. Generated apps emit a require_role dependency and create the user_roles table at startup. Proven end-to-end (normal user 403, admin 201, anon 401) + by the roles contract — IMPLEMENTED & proven",
              "role ASSIGNMENT now has admin-gated self-serve endpoints (POST /admin/roles/grant, POST /admin/roles/revoke, GET /admin/roles/{user_id}) generated whenever roles are in use, all behind require_role('admin') — proven by the role_admin contract + HTTP boundary e2e (anon 401, non-admin 403, admin 200, and a revoked user loses access). The FIRST admin is still seeded out-of-band via roles.grant() (bootstrap). Still pending: no per-row (object-level) role grants — gating is per entity/action"],
    "data_export": ["data-subject access/portability — generated apps expose GET /privacy/export returning the user's identity data AND domain-owned rows (the generated privacy.py covers the domain ORM registry the library export can't see). Proven end-to-end + by the domain_privacy contract — IMPLEMENTED & proven"],
    "account_deletion": ["right to erasure — generated apps expose POST /privacy/delete-account which erases the user's DOMAIN-owned rows (generated privacy.py) then library identity (sessions + user, with audit). Without the generated half, domain rows would be orphaned. Proven end-to-end: one user's data erased, session revoked, other users untouched — IMPLEMENTED & proven",
                         "still pending: erasure is by user_id ownership; rows merely referencing a user without a user_id column (e.g. free-text mentions) are not swept; deletion is hard-delete, not anonymization-in-place"],
    "build_report": ["per-build honest inventory — every EOS-generated app gets BUILD_REPORT.md + build_report.json listing entities, FK relationships, workflows, and per-entity security (auth/owner/encrypted/audited), computed from the resolved domain so it matches the emitted code; the 'not enforced' section is sourced from this registry. Verified against generated routes — IMPLEMENTED & proven",
                       "still pending: the report is written for the domain-driven (eos) path; template-assembled (assemble) apps do not yet get one, pending output-structure unification"],
    "workflow_engine": ["domain state-machine generation — an entity may declare a state_machine (field, initial, transitions, guards); the generator emits a defaulted+indexed status column, a transition() service method, and a POST /<entity>/{id}/transition route. Illegal transitions and unmet guards return 409; satisfying a guard unblocks the move. Proven by a live contract + end-to-end over HTTP on a generated bike-repair app — IMPLEMENTED & proven",
                         "still pending: guards now support same-row (field==value) AND cross-entity (related row status) checks; what remains is SIDE EFFECTS on transition (e.g. a damaged return auto-creating an incident + maintenance record and locking the tool), time-based transitions, and notifications"],
    "gen_models": ["relationship-aware schema generation — a client-supplied <entity>_id becomes an enforced ForeignKey (+ index); orphaned references are rejected with a clean 409; SQLite enforces FKs via PRAGMA; server-set owner user_id is indexed (cannot be orphaned). Proven end-to-end on a generated app + a live orphan-rejection contract — IMPLEMENTED & proven",
                   "many-to-many is now generated from a domain many_to_many declaration (join table with two CASCADE FKs + a uniqueness constraint, plus a link service and attach/detach/list routes) — proven by the many_to_many contract + HTTP e2e; still pending: relationships are otherwise inferred from <entity>_id naming (one-to-many / many-to-one), and richer declared relationship metadata (named roles, through-attributes on the join row) is not generated"],
    "stripe_webhooks": ["webhook signature verification + replay prevention + subscription lifecycle (activate/cancel/entitlement revoke) are implemented and proven by contracts and the entitlement-lifecycle workflow",
                        "the LIVE Stripe SDK call path is NOT wired — no real charges/subscriptions are created against Stripe's API; only the signature/lifecycle logic exists. No delayed-event reconciliation. Wire the stripe client + real webhook secret before taking payments"],
    "migration_substrate": ["generated apps are MIGRATION-FIRST: alembic.ini ships a default sqlalchemy.url (env.py overrides with $DATABASE_URL), boot runs `alembic upgrade head` in dev AND prod, and create_all is demoted to a check-first supplement that runs AFTER alembic — so `alembic upgrade head` works from an empty db with no DATABASE_URL and never hits a create_all-vs-migration `already exists` conflict. Found by external testing of v72; locked by the migration_substrate contract",
                            "still pending: the baseline migration covers the library/identity tables (audit_logs/sessions/users); feature/domain tables not yet in a migration are created by the check-first create_all supplement rather than baked into a migration — so production schema for those tables is create_all-managed, not alembic-managed"],
    "data_export": ["GET /privacy/export builds the full payload synchronously (fine for typical accounts); a STREAMING variant GET /privacy/export/stream now emits NDJSON row-by-row via a server-side cursor (constant memory, scales to large accounts) — proven by the streaming_export contract + HTTP e2e", "still pending: no background/async export JOB (the stream is still produced within the request, just not buffered); no resumable/checkpointed export"],
    "retention_policy": ["declared in domain policy but not enforced at runtime"],
    "document_store": ["durable RAG store with idempotent ingest + scored citations + tenant scope + retrieval logging — IMPLEMENTED & proven",
                       "still pending: embeddings default to local/deterministic (use OpenAI provider for real semantics); cosine scan is exact not ANN (use pgvector for scale); no async re-embed/migration job"],
    "providers": ["pluggable LLM+embedding providers (offline/anthropic/openai), offline refused in prod — IMPLEMENTED",
                  "still pending: streaming, per-call timeout/cost ceilings, retry policy on provider errors"],
    "migrations_alembic": ["Alembic migrations are the schema source of truth — proven: sqlite upgrade/downgrade roundtrip + ZERO drift vs models on real Postgres; generated apps ship a scoped baseline and apply migrations in production (create_all only in dev) — IMPLEMENTED & proven",
                           "still pending: the no-drift proof runs only when SCRAPYARD_TEST_PG_URL is set (sqlite roundtrip otherwise); generated-app baselines are autogenerated at assembly, not yet hand-reviewed; no multi-head/branch-merge policy; data migrations (vs schema) not templated"],
    "cache_client": ["real Redis-backed cache (env-resolved, ping-fail-fast) with the same interface as the in-memory cache — proven against live Redis: value shared across independent clients, TTL applied, delete/clear (namespace-scoped); in-memory cache is FORBIDDEN in production (fail-closed gate), proven at boot (prod+memory refuses, prod+redis boots) — IMPLEMENTED & proven",
                     "still pending: get_cache() is available but not auto-wired into generated routes/services (apps opt in); no automatic write-through invalidation by default; values are JSON-serializable only; a mid-request Redis outage raises (fail-closed) rather than degrading — Redis is on the critical path until L13 HA; no cache-stampede/lock protection"],
    "request_security": ["request-level enforcement wired into every generated app — RateLimitMiddleware rate-limits all routes against the distributed limiter (429 past capacity, keyed by JWT principal or client IP) and make_scoped_db sets per-request RLS context from the JWT principal so scoped tables isolate automatically; proven end-to-end on a live app under SCRAPYARD_RLS=enforce + a two-user isolation contract on real Postgres — IMPLEMENTED & proven",
                         "still pending: auto RLS context keys on the JWT principal only (a request bearing only an opaque session token won't auto-set context); caching is intentionally NOT auto-applied (route-specific); a runtime limiter error fails OPEN (boot still fails closed without Redis in prod); per-route cost/limit tiers are uniform (one global capacity)"],
    "frontend_react": ["real Vite + React frontend over the proven API — a genuine Vite project (JSX components, fetch API client targeting /health, /capabilities, /readyz, /auth/login) that BUILDS to a static bundle; proven by an actual `npm install` + `vite build` producing dist/index.html + a hashed JS bundle — IMPLEMENTED & proven (build executed in-sandbox)",
                       "still pending: not wired into auth token storage/refresh or per-template resource views (login + status only); no client-side routing/test suite; assets served separately from the API (CDN/static host), not bundled into the backend"],
    "scaling_lb": ["horizontal scaling — generated nginx load-balancer config is VALIDATED BY nginx itself (`nginx -t` successful), and a compose overlay runs nginx in front of N replicated web instances; scaling is correct because shared state lives in Postgres/Redis and the distributed rate limiter holds globally across instances (proven in rate_limit_distributed) — IMPLEMENTED & proven",
                   "still pending: live multi-instance round-robin not executed end-to-end in-sandbox (config is nginx-validated, not run); no autoscaling policy; nginx uses a static upstream (Docker-DNS/resolver for dynamic replica discovery not wired)"],
    "cdn_cache": ["CDN readiness — CacheControlMiddleware sets Cache-Control on safe GETs for configured prefixes so an edge can cache them; proven via TestClient (cacheable path tagged, dynamic/authenticated path untouched) — IMPLEMENTED & proven",
                  "still pending: no ETag/conditional-request (304) handling; the CDN itself is IaC-only (CloudFront declared, not provisioned); cacheable prefixes are configured manually"],
    "iac_terraform": ["infrastructure-as-code — generated Terraform parses (python-hcl2) declaring L6 compute (ECS), managed Postgres + Redis, an L11 load balancer, and an L10 CDN (CloudFront), with variables/outputs — IMPLEMENTED & parse-validated",
                      "still pending: NOT `terraform validate`-d or applied (no terraform binary / cloud creds in-sandbox); single AWS-flavored example (not multi-cloud); no remote state backend; networking/IAM/security-groups are minimal placeholders"],
    "ci_workflow": ["real CI — the library ships .github/workflows/ci.yml that runs the ACTUAL release gate (migration drift check + verify_build all + build_matrix + secure/fullstack runtime + assemble & docker build) against Postgres + Redis service containers; generated apps ship a CI that smokes, runs behavior checks, applies migrations on real Postgres, and builds the image — IMPLEMENTED & proven (gate commands reference real, existing tools)",
                    "still pending: not executed in-sandbox (no GitHub Actions runner / Docker daemon) — validated structurally + by tool-existence, not by a live workflow run; no CD/deploy stage; single Python version; no pip/build caching"],
    "deployment_files": ["writes a REAL production deployment into each assembled app — Dockerfile (non-root, /readyz healthcheck) + docker-compose.yml (app+postgres+redis, depends_on healthy, prod env wired) + .dockerignore + .env.production.example, and adds psycopg2/redis to requirements; proven: compose is valid YAML wiring the services AND the generated prod env satisfies the app's own fail-closed gate — IMPLEMENTED & proven",
                         "still pending: not built/run in-sandbox (no Docker daemon) — validated structurally + by gate-consistency, not by an actual `docker build`/`compose up`; single-node compose only (no k8s/helm); external secrets (crypto/SMTP/LLM keys) are operator-filled placeholders"],
    "backup": ["executable PostgreSQL backup/restore (pg_dump/pg_restore) — proven: a full dump -> drop -> restore roundtrip with data intact on real Postgres — IMPLEMENTED & proven",
               "still pending: no scheduling/cron wired; archives are not encrypted or shipped offsite by the tool (policy declares offsite but doesn't enforce it); full-DB restore only (no selective/PITR/WAL archiving)"],
    "readiness": ["deep readiness probe + fail-closed /readyz — proven: ready only when the DB is reachable AND migrations are at head (+ Redis when configured); pending migrations or an unreachable dependency returns 503; wired into generated apps (200 after prod migrate, 503 before) — IMPLEMENTED & proven",
                  "still pending: does not probe downstream providers (LLM/SMTP); no degraded-but-serving tier; assumes the app ships its alembic migrations on disk"],
    "error_reporting": ["real Sentry SDK integration — proven: an exception flows through the actual sentry_sdk pipeline to its transport (verified via in-memory transport, no network); structured JSON logs carry level + request context with privacy redaction; generated apps call init_sentry() at boot; production running with no exporter is surfaced as a warning — IMPLEMENTED & proven",
                        "still pending: only exception capture is wired (no breadcrumbs/performance/release tagging); no automatic FastAPI exception-handler -> reporter middleware by default; Prometheus metrics endpoint not auto-exposed; live Sentry delivery not exercised in-sandbox (sentry.io unreachable) — proven through the SDK transport instead"],
    "tracing": ["real OpenTelemetry tracing — proven: spans created and exported through the standard OTel SDK pipeline with correct parent/child linkage (verified via InMemorySpanExporter); init_otel() wires an OTLP exporter in production from OTEL_EXPORTER_OTLP_ENDPOINT — IMPLEMENTED & proven",
                "still pending: no auto-instrumentation of FastAPI/SQLAlchemy by default (spans are manual); OTLP export not exercised against a live collector in-sandbox (none running); fixed sampling"],
    "rate_limiting": ["distributed Redis token bucket via atomic Lua check-and-decrement — proven: the limit is enforced GLOBALLY across 3 independent instances under concurrent load (only capacity admitted, not N x capacity); in-memory per-process limiter is FORBIDDEN in production (fail-closed), proven at boot — IMPLEMENTED & proven",
                      "still pending: get_rate_limiter() is not auto-wired as middleware into generated apps (opt-in); token-bucket only (no sliding-window-log option); no per-route limit templating; refill timing assumes roughly-synced clocks across instances"],
    "row_level_security": ["database-enforced (PostgreSQL) per-tenant/per-owner isolation via ENABLE+FORCE RLS + fail-closed policies — proven AT THE DATABASE with raw SQL as a non-superuser owner: cross-tenant/owner read, write (DELETE-all), and INSERT (WITH CHECK) all blocked, zero rows when context unset; generated apps ship the module + an RLS-aware session and enforce it in production via apply_rls_existing (SCRAPYARD_RLS=enforce on Postgres), proven on saas_app — IMPLEMENTED & proven",
                           "still pending: per-request context must be set explicitly (via rls.py rls_session / set_context) — it is NOT yet auto-injected into every generated CRUD route, so the zero-config default app does app-level scoping unless wired; non-Postgres prod is refused (fail-closed) but RLS itself is Postgres-only; policies cover int user_id + text tenant_id columns (cast per column), not composite/UUID scopes yet"],
}


def _proven() -> set:
    out = "/tmp/_hr_proven.json"
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "verify_build.py"), "all", "--emit", out],
                   cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT}, capture_output=True, text=True)
    try:
        return set(json.load(open(out, encoding="utf-8")))
    except Exception:
        return set()


def _operational_caps() -> set:
    caps = set()
    fm = os.path.join(ROOT, "operations", "failure_models.json")
    dm = os.path.join(ROOT, "operations", "dependency_models.json")
    if os.path.exists(fm):
        caps.update(json.load(open(fm, encoding="utf-8")).get("failure_modes", {}).keys())
    if os.path.exists(dm):
        caps.update(json.load(open(dm, encoding="utf-8")).get("runtime_depends_on", {}).keys())
    return caps


def compute() -> dict:
    cat = json.load(open(os.path.join(ROOT, "catalog.json"), encoding="utf-8"))
    proven = _proven()
    operational = _operational_caps()
    rows = {}
    for layer, parts in cat["layers"].items():
        for p in parts:
            name = p["name"]
            implemented = p.get("status") == "core"
            verified = name in proven
            hardened = name in HARDENED
            op = name in operational
            if hardened and op:
                tier = "operational"
            elif hardened:
                tier = "hardened"
            elif verified:
                tier = "verified"
            elif implemented:
                tier = "implemented"
            else:
                tier = "unknown"
            row = {"layer": layer, "implemented": implemented, "verified": verified,
                   "hardened": hardened, "operational": op, "maturity": tier}
            if name in HARDENED:
                row["hardened_evidence"] = HARDENED[name]
            if name in KNOWN_GAPS:
                row["hardening_gaps"] = KNOWN_GAPS[name]
            rows[name] = row
    tiers = {}
    for r in rows.values():
        tiers[r["maturity"]] = tiers.get(r["maturity"], 0) + 1
    totals = {
        "count": len(rows),
        "implemented": sum(1 for r in rows.values() if r["implemented"]),
        "verified": sum(1 for r in rows.values() if r["verified"]),
        "hardened": sum(1 for r in rows.values() if r["hardened"]),
        "operational": sum(1 for r in rows.values() if r["operational"]),
        "by_maturity": tiers,
    }
    return {"schema": "scrapyard/hardening@1",
            "note": "implemented/verified COMPUTED; hardened requires registered evidence (deliberately near-zero today); operational COMPUTED from operations/ models.",
            "totals": totals, "capabilities": dict(sorted(rows.items()))}


def write_markdown(data: dict) -> str:
    t = data["totals"]
    n = t["count"]
    lines = ["# Hardening & Maturity", "",
             f"_Computed across {n} capabilities. \"Hardened\" is honest: it requires registered",
             "evidence (rotation/recovery/tamper/edge coverage), which most capabilities do not",
             'yet have. This is the point — "core" was never "production".', "", "## Maturity tiers", ""]
    for tier in ("implemented", "verified", "hardened", "operational"):
        c = t["by_maturity"].get(tier, 0)
        lines.append(f"- **{tier}:** {c}")
    lines += ["",
              f"- implemented (in catalog): {t['implemented']}/{n}",
              f"- verified (behavior contract): {t['verified']}/{n}",
              f"- hardened (registered evidence): {t['hardened']}/{n}",
              f"- operational (failure/deps declared): {t['operational']}/{n}",
              "", "## Known hardening gaps (security-critical)", ""]
    for name, row in data["capabilities"].items():
        if row.get("hardening_gaps"):
            lines.append(f"- **{name}**: " + "; ".join(row["hardening_gaps"]))
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    data = compute()
    if "--write" in sys.argv:
        json.dump(data, open(os.path.join(ROOT, "hardening_registry.json"), "w", encoding="utf-8"), indent=2)
        open(os.path.join(ROOT, "HARDENING.md"), "w", encoding="utf-8").write(write_markdown(data))
        print("wrote hardening_registry.json + HARDENING.md")
    t = data["totals"]
    print(f"implemented {t['implemented']} · verified {t['verified']} · "
          f"hardened {t['hardened']} · operational {t['operational']} · tiers {t['by_maturity']}")
