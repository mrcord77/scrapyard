#!/usr/bin/env python3
"""
scaffold_parts.py — bootstrap the scrapyard.

Single source of truth for the parts taxonomy. Running this writes one
self-describing Python module per part into ./scrapyard/<layer>/<name>.py,
*only if it does not already exist* (so it never clobbers real implementations).

Each part carries a machine-readable metadata in its module docstring, fenced
by PART-META-JSON markers, which tools/index_catalog.py reads to build the
catalog. Re-run any time you add an entry below; it fills in only what's missing.

    python tools/scaffold_parts.py
"""
from __future__ import annotations
import json
import os
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "scrapyard")

META_OPEN = "### PART-META-JSON"
META_CLOSE = "### END-PART-META"

# (name, purpose, status, [deps]) — status: "core" (hand-implemented) | "skeleton"
# "+" in a purpose marks an addition beyond the original GPT map.
TAXONOMY: dict[str, list[tuple]] = {
    "foundation": [
        ("app_scaffold", "Minimal application entrypoint wiring config+logging+app_factory.", "skeleton", []),
        ("config", "Typed settings loaded from env/.env with validation.", "core", ["pydantic-settings"]),
        ("env_loading", "Locate and load .env files across environments.", "skeleton", ["python-dotenv"]),
        ("logging_setup", "Structured, JSON-capable logging with request correlation.", "core", []),
        ("health", "Liveness/readiness checks aggregating dependency probes.", "core", []),
        ("settings_validation", "+ Fail-fast validation of required settings at boot.", "skeleton", []),
        ("dependency_container", "+ Tiny service registry / DI container.", "skeleton", []),
        ("idempotency", "+ Idempotency-key store to dedupe unsafe retried requests.", "skeleton", []),
        ("error_taxonomy", "+ Canonical app error classes mapped to HTTP + codes.", "skeleton", []),
    ],
    "api": [
        ("app_factory", "FastAPI application factory wiring middleware, errors, health.", "core", ["fastapi"]),
        ("routers", "Convention for grouping/mounting versioned routers.", "skeleton", ["fastapi"]),
        ("middleware", "Common middleware stack (timing, body limits, gzip).", "skeleton", ["fastapi"]),
        ("validation", "Reusable request/response model patterns and validators.", "skeleton", ["pydantic"]),
        ("error_handling", "Exception handlers producing consistent error envelopes.", "core", ["fastapi"]),
        ("request_context", "+ Per-request ID + context var propagated to logs.", "core", ["fastapi"]),
        ("pagination_params", "+ Shared query params for page/cursor pagination.", "skeleton", ["fastapi"]),
        ("versioning", "+ URL/header API versioning helpers.", "skeleton", ["fastapi"]),
        ("openapi_custom", "+ Customize OpenAPI schema, tags, security schemes.", "skeleton", ["fastapi"]),
    ],
    "database": [
        ("db_session", "SQLAlchemy engine + session factory + get_db dependency.", "core", ["sqlalchemy"]),
        ("base_model", "Declarative base with primary key + common helpers.", "core", ["sqlalchemy"]),
        ("migrations", "Alembic setup conventions for schema migrations.", "skeleton", ["alembic"]),
        ("repository", "Generic typed repository over a model.", "core", ["sqlalchemy"]),
        ("transactions", "Transaction + unit-of-work context managers.", "skeleton", ["sqlalchemy"]),
        ("seed_data", "Idempotent seed/fixture loader for dev + tests.", "skeleton", ["sqlalchemy"]),
        ("pagination", "Limit/offset + keyset (cursor) pagination helpers.", "core", ["sqlalchemy"]),
        ("soft_delete", "Mixin + query filter for soft deletes.", "core", ["sqlalchemy"]),
        ("timestamps", "created_at/updated_at mixin with auto-touch.", "core", ["sqlalchemy"]),
        ("unit_of_work", "+ Explicit UoW boundary around repositories.", "skeleton", ["sqlalchemy"]),
        ("audit_mixin", "+ created_by/updated_by + change tracking mixin.", "skeleton", ["sqlalchemy"]),
        ("query_helpers", "+ Common filter/sort/search query builders.", "skeleton", ["sqlalchemy"]),
    ],
    "identity": [
        ("users", "User model + core user service (create/find/update).", "skeleton", ["sqlalchemy"]),
        ("auth_routes", "Login/logout/refresh route handlers (login_routes).", "skeleton", ["fastapi"]),
        ("session_manager", "Server-side session issue/lookup/revoke.", "skeleton", []),
        ("jwt_manager", "Encode/decode signed access + refresh tokens.", "core", ["pyjwt"]),
        ("password_reset", "Token-based password reset request + confirm flow.", "skeleton", []),
        ("email_verification", "Email confirmation token issue + verify.", "skeleton", []),
        ("mfa_totp", "TOTP enrollment + verification (RFC 6238).", "skeleton", ["pyotp"]),
        ("oauth_google", "Google OAuth2 sign-in (authorize + callback).", "skeleton", ["authlib"]),
        ("password_hashing", "Hash + verify passwords with Argon2/bcrypt.", "core", ["passlib[argon2]"]),
        ("account_lockout", "+ Lock accounts after repeated failed logins.", "skeleton", []),
    ],
    "authorization": [
        ("roles", "Role definitions + assignment to principals.", "skeleton", []),
        ("permissions", "Permission checks + FastAPI require() dependency (RBAC).", "core", ["fastapi"]),
        ("feature_gates", "Boolean/percentage feature flags per user/tenant.", "skeleton", []),
        ("tenant_access", "Authorize a principal against a tenant boundary.", "skeleton", []),
        ("admin_access", "Guard admin-only surfaces.", "skeleton", ["fastapi"]),
        ("entitlement_gate", "Gate features by billing plan/entitlement.", "core", []),
    ],
    "billing": [
        ("stripe_checkout", "Create Stripe Checkout sessions for plans.", "skeleton", ["stripe"]),
        ("stripe_webhooks", "Verify + dispatch Stripe webhook events.", "skeleton", ["stripe", "fastapi"]),
        ("subscriptions", "Subscription model + lifecycle state.", "skeleton", ["sqlalchemy"]),
        ("subscription_status", "Resolve a customer's current plan/status.", "skeleton", []),
        ("invoices", "List/fetch invoices for a customer.", "skeleton", ["stripe"]),
        ("invoice_portal", "Stripe billing portal session creation.", "skeleton", ["stripe"]),
        ("cancellation_flow", "Cancel/downgrade with grace + reason capture.", "skeleton", ["stripe"]),
        ("entitlements", "Map plan -> entitlements/limits.", "skeleton", []),
        ("usage_metering", "+ Record metered usage for usage-based billing.", "skeleton", []),
        ("stripe_tax", "+ Enable Stripe Tax at checkout + register collection per nexus state.", "core", ["stripe"]),
    ],
    "admin": [
        ("dashboards", "Admin overview metrics aggregation.", "skeleton", []),
        ("user_management", "Search/suspend/restore/edit users (admin).", "skeleton", []),
        ("audit_logs", "Append-only admin action audit log.", "skeleton", ["sqlalchemy"]),
        ("moderation_tools", "Flag/review/resolve user-generated content.", "skeleton", []),
        ("impersonation", "+ Safe, logged user impersonation for support.", "skeleton", []),
        ("admin_routes", "+ Operational admin API: /admin/status (live) + /admin/jobs.", "core", ["fastapi", "sqlalchemy"]),
    ],
    "content": [
        ("cms", "Generic content model + publish workflow.", "skeleton", ["sqlalchemy"]),
        ("markdown_pages", "Render markdown pages with front-matter.", "skeleton", ["markdown"]),
        ("blog", "Blog posts with tags, slugs, drafts.", "skeleton", ["sqlalchemy"]),
        ("media_library", "Catalog uploaded media with metadata.", "skeleton", ["sqlalchemy"]),
        ("seo_metadata", "Per-page title/description/OG/Twitter tags.", "skeleton", []),
        ("sitemap", "+ Generate sitemap.xml + robots.txt.", "skeleton", []),
        ("content_routes", "+ Public content API (list/read published) + key-gated authoring.", "core", ["fastapi", "sqlalchemy"]),
    ],
    "communication": [
        ("email", "Transactional email send via pluggable provider.", "skeleton", []),
        ("sms", "SMS send via pluggable provider.", "skeleton", []),
        ("push_notifications", "Web/mobile push dispatch.", "skeleton", []),
        ("templates", "Render notification templates (text/html).", "skeleton", ["jinja2"]),
        ("unsubscribe_handling", "Honor unsubscribe + suppression list.", "skeleton", []),
        ("notification_center", "+ In-app notification inbox model + feed.", "skeleton", ["sqlalchemy"]),
    ],
    "files": [
        ("uploads", "Validated multipart upload handling.", "skeleton", ["fastapi"]),
        ("image_processing", "Resize/convert/strip-EXIF images.", "skeleton", ["pillow"]),
        ("virus_scanning", "Scan uploads via ClamAV/provider before persist.", "skeleton", []),
        ("storage_adapters", "S3/GCS/local storage behind one interface.", "skeleton", ["boto3"]),
        ("signed_urls", "+ Time-limited signed download/upload URLs.", "skeleton", []),
    ],
    "search": [
        ("filters", "Composable, safe filter spec -> query.", "skeleton", []),
        ("full_text_search", "Full-text search (pg tsvector / external engine).", "skeleton", ["sqlalchemy"]),
        ("search_pagination", "Pagination tuned for search result sets.", "skeleton", []),
        ("sorting", "Whitelisted multi-field sorting.", "skeleton", []),
        ("saved_searches", "Persist + replay user search definitions.", "skeleton", ["sqlalchemy"]),
        ("faceted_search", "+ Facet counts/aggregations for filters.", "skeleton", []),
    ],
    "jobs": [
        ("background_tasks", "Fire-and-forget tasks off the request path.", "skeleton", []),
        ("cron_jobs", "Declarative scheduled job registry.", "skeleton", []),
        ("queues", "Enqueue/consume via Redis/RQ/Celery adapter.", "skeleton", ["redis"]),
        ("retries", "Backoff + jitter retry wrapper for tasks.", "skeleton", []),
        ("scheduled_workflows", "Multi-step scheduled workflow runner.", "skeleton", []),
        ("dead_letter", "+ Dead-letter capture for exhausted jobs.", "skeleton", []),
        ("db_queue", "+ Durable DB-backed job queue: locking, retry/backoff, dead-letter, idempotency.", "core", ["sqlalchemy"]),
        ("worker", "+ Worker loop that drains the durable queue (CLI: python -m scrapyard.jobs.worker).", "core", ["sqlalchemy"]),
        ("jobs_admin_routes", "+ Admin API to inspect/retry/cancel durable jobs.", "core", ["fastapi", "sqlalchemy"]),
    ],
    "ai": [
        ("llm_client", "Provider-agnostic chat/completions client.", "skeleton", ["anthropic"]),
        ("prompt_registry", "Versioned, named prompt templates.", "skeleton", ["jinja2"]),
        ("rag", "Retrieval-augmented generation orchestration.", "skeleton", []),
        ("tool_calling", "Register + dispatch model tool calls safely.", "skeleton", []),
        ("token_cost_logging", "Log tokens + $ cost per call/user.", "skeleton", ["sqlalchemy"]),
        ("embeddings", "+ Create + cache text embeddings.", "skeleton", []),
        ("vector_store", "+ Upsert/query vectors behind one interface.", "skeleton", []),
        ("guardrails", "+ Validate/repair model output to a schema.", "skeleton", ["pydantic"]),
        ("streaming", "+ Stream tokens to client via SSE.", "skeleton", []),
        ("eval_harness", "+ Run prompt evals against fixtures.", "skeleton", []),
        ("ai_routes", "+ AI API: /ai/status, /ai/documents, /ai/query (guardrailed RAG, offline-honest).", "core", ["fastapi", "sqlalchemy"]),
        ("providers", "+ Pluggable LLM+embedding providers (offline/anthropic/openai), prod-fail-closed.", "core", []),
        ("chunking", "+ Sentence-aware text chunking with overlap for RAG.", "core", []),
        ("document_store", "+ Durable document/chunk storage + scored retrieval + retrieval logs.", "core", ["sqlalchemy"]),
        ("rag_service", "+ Grounded, cited answers with usage accounting + offline honesty.", "core", []),
    ],
    "marketplace": [
        ("listings", "+ Marketplace listings: list/detail (public) + seller-key-gated create.", "core", ["fastapi", "sqlalchemy"]),
    ],
    "analytics": [
        ("event_tracking", "Capture typed product events.", "skeleton", ["sqlalchemy"]),
        ("funnels", "Define + compute conversion funnels.", "skeleton", []),
        ("usage_metrics", "Aggregate active users / feature usage.", "skeleton", []),
        ("reports", "Scheduled/exportable report builder.", "skeleton", []),
        ("ab_testing", "+ Assign + measure experiment variants.", "skeleton", []),
    ],
    "security": [
        ("rate_limiting", "Token-bucket rate limiter (in-mem/redis).", "core", []),
        ("cors", "Configured CORS policy helper.", "skeleton", ["fastapi"]),
        ("csrf", "Double-submit CSRF protection for cookie auth.", "skeleton", []),
        ("security_headers", "CSP/HSTS/frame/referrer security headers.", "core", ["fastapi"]),
        ("secrets", "Load secrets from env/manager; never log them.", "skeleton", []),
        ("input_sanitization", "Sanitize/escape untrusted input + HTML.", "skeleton", ["bleach"]),
        ("password_policy", "+ Enforce password strength + breach check.", "skeleton", []),
        ("field_encryption", "+ Encrypt sensitive columns at rest.", "skeleton", ["cryptography"]),
        ("signed_cookies", "+ Tamper-evident signed cookies.", "skeleton", ["itsdangerous"]),
        ("crypto_agility", "+ Named swappable cipher suites + backend selection + honest PQC tiering.", "core", []),
        ("pq_envelope", "+ Hybrid post-quantum envelope encryption (X25519 + ML-KEM-768 -> AES-256-GCM).", "core", ["cryptography", "kyber-py"]),
        ("pq_signing", "+ Hybrid post-quantum signatures (Ed25519 + ML-DSA-65) for audit witness/attestation.", "core", ["cryptography", "dilithium-py"]),
        ("pq_field_encryption", "+ Encrypt columns at rest under hybrid PQ key transport (envelope-of-DEK, rotatable).", "core", ["cryptography", "kyber-py", "sqlalchemy"]),
    ],
    "compliance": [
        ("privacy_policy_hooks", "Surface + version privacy policy acceptance.", "skeleton", []),
        ("data_export", "Export a user's data (DSAR/portability).", "skeleton", []),
        ("account_deletion", "Hard/soft delete + downstream purge.", "skeleton", []),
        ("consent_logs", "Record consent grants/revocations with proof.", "skeleton", ["sqlalchemy"]),
        ("gdpr_dsr", "+ Intake + fulfill data-subject requests.", "skeleton", []),
        ("retention_policy", "+ Auto-expire data per retention rules.", "skeleton", []),
        ("sales_tax_nexus", "+ US economic-nexus sales-tax exposure map (where you must register).", "core", []),
        ("sales_tax_filing_calendar", "+ Per-state sales-tax remittance filing calendar.", "core", []),
    ],
    "frontend": [
        ("navbars", "Responsive nav + mobile menu block.", "skeleton", ["react"]),
        ("dashboards", "Dashboard shell with cards/charts slots.", "skeleton", ["react"]),
        ("forms", "Accessible form fields + validation display.", "skeleton", ["react"]),
        ("tables", "Sortable/paginated data table.", "skeleton", ["react"]),
        ("pricing_pages", "Pricing tiers + checkout CTA block.", "skeleton", ["react"]),
        ("settings_pages", "Account/settings layout with sections.", "skeleton", ["react"]),
        ("auth_pages", "+ Login/signup/reset UI blocks.", "skeleton", ["react"]),
        ("empty_states", "+ Reusable empty/error/loading states.", "skeleton", ["react"]),
    ],
    "deployment": [
        ("docker", "Multistage Dockerfile + compose for the stack.", "skeleton", []),
        ("render", "render.yaml blueprint.", "skeleton", []),
        ("railway", "Railway service + variables config.", "skeleton", []),
        ("vercel", "vercel.json for frontend deploys.", "skeleton", []),
        ("github_actions", "CI: lint/test/build/deploy workflow.", "skeleton", []),
        ("backups", "Scheduled DB + media backup scripts.", "skeleton", []),
        ("healthcheck_probe", "+ Container/orchestrator probe script.", "skeleton", []),
    ],
    "testing": [
        ("smoke_checks", "Post-deploy smoke test of key routes.", "skeleton", ["httpx"]),
        ("link_checks", "Crawl + verify internal/external links.", "skeleton", ["httpx"]),
        ("payment_checks", "Verify checkout/webhook path in test mode.", "skeleton", []),
        ("auth_checks", "Verify login/refresh/permission paths.", "skeleton", []),
        ("factories", "+ Model factories/fixtures for tests.", "skeleton", []),
        ("contract_tests", "+ Validate responses against OpenAPI schema.", "skeleton", []),
    ],
    "caching": [
        ("cache_client", "+ Unified cache interface (memory/redis).", "skeleton", ["redis"]),
        ("cached_decorator", "+ Memoize function results with TTL.", "skeleton", []),
        ("cache_invalidation", "+ Tag-based invalidation helpers.", "skeleton", []),
    ],
    "observability": [
        ("tracing", "+ OpenTelemetry spans for requests/db/llm.", "skeleton", ["opentelemetry-api"]),
        ("metrics", "+ Prometheus counters/histograms.", "skeleton", ["prometheus-client"]),
        ("error_reporting", "+ Capture exceptions to Sentry/provider.", "skeleton", []),
        ("structured_logging", "+ Log helpers that emit structured events.", "skeleton", []),
    ],
    "realtime": [
        ("websocket_manager", "+ Track + broadcast over WebSocket connections.", "skeleton", ["fastapi"]),
        ("sse_stream", "+ Server-Sent Events response helper.", "skeleton", ["fastapi"]),
    ],
    "messaging": [
        ("event_bus", "+ In-process pub/sub for domain events.", "skeleton", []),
        ("webhooks_outbound", "+ Signed, retried outbound webhook delivery.", "skeleton", []),
        ("webhooks_inbound", "+ Verify + route inbound webhooks.", "skeleton", ["fastapi"]),
    ],
    "multitenancy": [
        ("tenant_context", "+ Resolve + carry current tenant per request.", "skeleton", []),
        ("tenant_isolation", "+ Scope queries to the active tenant.", "skeleton", ["sqlalchemy"]),
        ("per_tenant_config", "+ Per-tenant settings/overrides.", "skeleton", []),
    ],
    "localization": [
        ("i18n", "+ Translate keys with locale fallback.", "skeleton", ["babel"]),
        ("translations", "+ Catalog format + loader for messages.", "skeleton", []),
        ("locale_middleware", "+ Detect locale from header/user.", "skeleton", ["fastapi"]),
    ],
}


def metadata(layer: str, name: str, purpose: str, status: str, deps: list[str]) -> dict:
    pkg_path = f"scrapyard.{layer}.{name}"
    return {
        "name": name,
        "layer": layer,
        "purpose": purpose.lstrip("+ ").strip(),
        "addition": purpose.strip().startswith("+"),
        "status": status,
        "dependencies": deps,
        "inputs": "See function signatures in this module.",
        "outputs": "See function/return annotations in this module.",
        "files_created": [],
        "security_notes": "Review before production. Validate all external input; never log secrets/PII.",
        "ai_usage": f"Import what you need from `{pkg_path}`; read this metadata, wire the example, install dependencies.",
        "example": f"from {pkg_path} import *  # see module for concrete symbols",
        "import_path": pkg_path,
    }


def part_source(m: dict) -> str:
    # HONESTY GUARD: whatever the taxonomy says (it is a historical record of
    # intent), a freshly scaffolded file contains only a NotImplementedError
    # stub — its metadata MUST say "skeleton". Status becomes "core" only when
    # a real implementation lands and tools/index_catalog.py verifies it.
    m = {**m, "status": "skeleton"}
    block = json.dumps(m, indent=2)
    body = (
        "from __future__ import annotations\n\n"
        f'STATUS = "{m["status"]}"\n\n'
        "# This is a drop-in scrapyard part. Its contract lives in the metadata above.\n"
        "# Implement against the documented inputs/outputs, then flip status to 'core'\n"
        "# in tools/scaffold_parts.py and re-run tools/index_catalog.py.\n\n\n"
        "def _not_implemented(*_a, **_k):\n"
        f'    raise NotImplementedError("scrapyard part not yet implemented: {m["import_path"]}")\n'
    )
    return (
        f'"""\n{m["name"]} — {m["purpose"]}\n\n'
        f"{META_OPEN}\n{block}\n{META_CLOSE}\n"
        f'"""\n{body}'
    )


def main() -> None:
    created, skipped = 0, 0
    open(os.path.join(PKG, "__init__.py"), "a", encoding="utf-8").close() if os.path.isdir(PKG) else os.makedirs(PKG, exist_ok=True)
    with open(os.path.join(PKG, "__init__.py"), "w", encoding="utf-8") as f:
        f.write('"""scrapyard — a parts catalog you assemble apps from."""\n__version__ = "0.1.0"\n')
    for layer, parts in TAXONOMY.items():
        ldir = os.path.join(PKG, layer)
        os.makedirs(ldir, exist_ok=True)
        with open(os.path.join(ldir, "__init__.py"), "w", encoding="utf-8") as f:
            f.write(f'"""{layer} layer parts."""\n')
        for name, purpose, status, deps in parts:
            path = os.path.join(ldir, f"{name}.py")
            if os.path.exists(path):
                skipped += 1
                continue
            m = metadata(layer, name, purpose, status, deps)
            with open(path, "w", encoding="utf-8") as f:
                f.write(part_source(m))
            created += 1
    total = sum(len(v) for v in TAXONOMY.values())
    print(f"layers={len(TAXONOMY)} parts={total} created={created} skipped(existing)={skipped}")


if __name__ == "__main__":
    main()
