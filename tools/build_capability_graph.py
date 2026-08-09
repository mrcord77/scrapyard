#!/usr/bin/env python3
"""
build_capability_graph.py — author the capability graph above the parts.

A *capability* is a stable, self-describing name. Two kinds:

  concrete  — provided by exactly one part. Capability name == part name
              (layer-qualified only when a bare name collides across layers).
              May declare `requires`: other capabilities it needs at runtime.

  meta      — a subsystem. Provided by NO single part; defined purely by the
              set of capabilities it pulls in. This is the "Subsystems" tier:
                  Pattern -> Subsystems(meta) -> Parts(concrete) -> Code

Everything here is validated against catalog.json: every concrete capability
must map to a real part, and every `requires` target must resolve to a real
capability (concrete or meta). A dangling edge is a hard error — the graph is
never written half-valid.

    python tools/build_capability_graph.py        # build + validate + write
    python tools/build_capability_graph.py --check # validate only, no write

Output: capabilities/capabilities.json (schema scrapyard/capabilities@1)
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(ROOT, "catalog.json")
OUT_DIR = os.path.join(ROOT, "capabilities")
OUT = os.path.join(OUT_DIR, "capabilities.json")

# ---------------------------------------------------------------------------
# Concrete inter-part edges. Keyed by capability name (bare part name, or
# layer-qualified when the name collides). Values are capability names this
# part needs. Authored only where the dependency is real and known; skeleton
# parts with unknown wiring are left edge-free rather than guessed at.
# ---------------------------------------------------------------------------
PART_REQUIRES: dict[str, list[str]] = {
    # api
    "app_factory":       ["config", "logging_setup", "health", "request_context", "error_handling"],
    "error_handling":    ["error_taxonomy"],
    "routers":           ["app_factory"],
    "versioning":        ["routers"],
    "openapi_custom":    ["app_factory"],
    # database
    "repository":        ["db_session", "base_model"],
    "soft_delete":       ["base_model"],
    "timestamps":        ["base_model"],
    "audit_mixin":       ["base_model"],
    "unit_of_work":      ["db_session"],
    "transactions":      ["db_session"],
    "query_helpers":     ["db_session"],
    "seed_data":         ["db_session", "base_model"],
    "migrations":        ["db_session"],
    # identity
    "jwt_manager":       ["config"],
    "auth_routes":       ["users", "password_hashing", "jwt_manager", "session_manager"],
    "password_reset":    ["users", "email"],
    "email_verification": ["users", "email"],
    "mfa_totp":          ["users"],
    "oauth_google":      ["users", "session_manager"],
    "account_lockout":   ["users", "rate_limiting"],
    "session_manager":   ["users"],
    # authorization
    "roles":             ["users"],
    "permissions":       ["roles"],
    "admin_access":      ["permissions"],
    "tenant_access":     ["tenant_context", "permissions"],
    "entitlement_gate":  ["subscription_status"],
    "feature_gates":     ["entitlement_gate"],
    # security — post-quantum
    "pq_envelope":        ["crypto_agility"],
    "pq_signing":         ["crypto_agility"],
    "pq_field_encryption": ["pq_envelope", "crypto_agility"],
    "audit_logs":         ["pq_signing"],  # tamper-evident witness uses hybrid PQ signing
    # jobs — durable path
    "db_queue":           ["db_session", "base_model"],
    "worker":             ["db_queue"],
    "jobs_admin_routes":  ["db_queue"],
    "admin_routes":       ["db_session"],
    "content_routes":     ["db_session", "base_model", "blog"],
    "ai_routes":          ["document_store", "rag_service", "providers", "guardrails"],
    "rag_service":        ["providers", "document_store"],
    "document_store":     ["db_session", "base_model", "chunking", "embeddings"],
    "providers":          ["embeddings"],
    "listings":           ["db_session", "base_model"],
    # billing
    "subscriptions":     ["users"],
    "subscription_status": ["subscriptions"],
    "stripe_checkout":   ["subscriptions", "users"],
    "stripe_webhooks":   ["subscriptions", "subscription_status"],
    "invoices":          ["subscriptions"],
    "invoice_portal":    ["invoices"],
    "cancellation_flow": ["subscriptions"],
    "entitlements":      ["subscription_status"],
    "usage_metering":    ["subscriptions"],
    # ai
    "rag":               ["embeddings", "vector_store", "llm_client"],
    "embeddings":        ["llm_client"],
    "tool_calling":      ["llm_client"],
    "streaming":         ["llm_client", "sse_stream"],
    "guardrails":        ["llm_client"],
    "eval_harness":      ["llm_client", "prompt_registry"],
    "token_cost_logging": ["llm_client"],
    # admin
    "user_management":   ["users", "roles"],
    "audit_logs":        ["base_model"],
    "moderation_tools":  ["users"],
    "impersonation":     ["users", "session_manager", "audit_logs"],
    # admin.dashboards vs frontend.dashboards collide -> qualified keys
    "admin.dashboards":  ["audit_logs", "usage_metrics"],
    # compliance
    "data_export":       ["users"],
    "account_deletion":  ["users", "data_export"],
    "gdpr_dsr":          ["data_export", "account_deletion", "consent_logs"],
    "consent_logs":      ["base_model"],
    "retention_policy":  ["base_model"],
    # content
    "blog":              ["cms", "markdown_pages"],
    "sitemap":           ["seo_metadata"],
    "media_library":     ["uploads"],
    # search
    "faceted_search":    ["full_text_search"],
    "saved_searches":    ["full_text_search", "users"],
    "search_pagination": ["full_text_search"],
    # jobs
    "scheduled_workflows": ["cron_jobs", "queues"],
    "dead_letter":       ["queues"],
    "retries":           ["queues"],
    "background_tasks":  ["queues"],
    # multitenancy
    "tenant_isolation":  ["tenant_context"],
    "per_tenant_config": ["tenant_context"],
    # files
    "signed_urls":       ["storage_adapters"],
    "uploads":           ["storage_adapters"],
    "image_processing":  ["uploads"],
    "virus_scanning":    ["uploads"],
    # communication
    "notification_center": ["users"],
    "unsubscribe_handling": ["email", "users"],
    "push_notifications": ["users"],
    # caching
    "cached_decorator":  ["cache_client"],
    "cache_invalidation": ["cache_client"],
    # observability
    "tracing":           ["structured_logging"],
    "error_reporting":   ["structured_logging"],
    # messaging
    "webhooks_outbound": ["event_bus"],
    "webhooks_inbound":  ["event_bus"],
    # localization
    "locale_middleware": ["i18n"],
    "translations":      ["i18n"],
    # frontend
    "auth_pages":        ["forms"],
    "pricing_pages":     ["forms"],
    "settings_pages":    ["forms"],
    "frontend.dashboards": ["tables"],
}

# ---------------------------------------------------------------------------
# Meta-capabilities (subsystems). Each is defined by what it requires.
# ---------------------------------------------------------------------------
META: dict[str, dict] = {
    "foundation_core": {
        "description": "Config, logging, health, error taxonomy — every app needs this.",
        "requires": ["config", "logging_setup", "health", "error_taxonomy", "settings_validation"],
    },
    "web_api": {
        "description": "HTTP layer: app factory, routing, validation, request context, errors.",
        "requires": ["foundation_core", "app_factory", "request_context", "error_handling",
                     "routers", "validation", "pagination_params", "middleware"],
    },
    "persistence_core": {
        "description": "Relational persistence: sessions, base model, mixins, repository, pagination.",
        "requires": ["db_session", "base_model", "timestamps", "soft_delete",
                     "pagination", "repository", "transactions", "migrations"],
    },
    "security_baseline": {
        "description": "Always-on security: headers, CORS, rate limiting, sanitization, secrets.",
        "requires": ["security_headers", "cors", "rate_limiting", "input_sanitization", "secrets"],
    },
    "authentication": {
        "description": "Who the user is: accounts, password + token auth, verification, recovery.",
        "requires": ["users", "password_hashing", "password_policy", "jwt_manager",
                     "session_manager", "auth_routes", "email_verification",
                     "password_reset", "account_lockout"],
    },
    "authorization_rbac": {
        "description": "What the user may do: roles, permissions, admin gating.",
        "requires": ["roles", "permissions", "admin_access"],
    },
    "billing_stripe": {
        "description": "Money: Stripe checkout, webhooks, subscriptions, invoices, entitlement gating.",
        "requires": ["subscriptions", "subscription_status", "stripe_checkout", "stripe_webhooks",
                     "invoices", "cancellation_flow", "entitlements", "entitlement_gate",
                     "sales_tax_compliance"],
    },
    "sales_tax_compliance": {
        "description": "US economic-nexus (post-Wayfair) sales tax: exposure map (where you must register), Stripe Tax collection at checkout, and the remittance filing calendar. Required wherever money is collected across state lines — a missed obligation is a liability, not an oversight.",
        "requires": ["sales_tax_nexus", "stripe_tax", "sales_tax_filing_calendar"],
    },
    "metering_billing": {
        "description": "Usage-based billing on top of subscriptions.",
        "requires": ["billing_stripe", "usage_metering", "usage_metrics"],
    },
    "multitenancy_core": {
        "description": "Tenant boundary: context, isolation, per-tenant config, tenant-scoped access.",
        "requires": ["tenant_context", "tenant_isolation", "per_tenant_config", "tenant_access"],
    },
    "admin_console": {
        "description": "Back-office: audit logs, dashboards, user management, moderation, impersonation.",
        "requires": ["audit_logs", "admin.dashboards", "user_management", "moderation_tools", "impersonation"],
    },
    "compliance_gdpr": {
        "description": "Data-subject rights: export, deletion, consent, retention, DSR handling.",
        "requires": ["gdpr_dsr", "data_export", "account_deletion", "consent_logs",
                     "retention_policy", "privacy_policy_hooks"],
    },
    "comms_core": {
        "description": "Outbound communication: email, templates, notifications, unsubscribe.",
        "requires": ["email", "templates", "notification_center", "unsubscribe_handling"],
    },
    "files_core": {
        "description": "User files: uploads, storage adapters, signed URLs.",
        "requires": ["uploads", "storage_adapters", "signed_urls"],
    },
    "search_core": {
        "description": "Find things: full-text search, filters, sorting, paginated results.",
        "requires": ["full_text_search", "filters", "sorting", "search_pagination"],
    },
    "search_faceted": {
        "description": "Faceted/aggregated search for catalogs and directories.",
        "requires": ["search_core", "faceted_search", "saved_searches"],
    },
    "content_core": {
        "description": "Publishing: CMS, markdown pages, SEO metadata, sitemap.",
        "requires": ["cms", "markdown_pages", "seo_metadata", "sitemap"],
    },
    "jobs_core": {
        "description": "Async work: queues, background tasks, retries, scheduling, dead-letter.",
        "requires": ["queues", "background_tasks", "retries", "cron_jobs",
                     "scheduled_workflows", "dead_letter"],
    },
    "ai_core": {
        "description": "LLM plumbing: client, prompt registry, cost logging, guardrails.",
        "requires": ["llm_client", "prompt_registry", "token_cost_logging", "guardrails"],
    },
    "rag_stack": {
        "description": "Retrieval-augmented generation: embeddings, vector store, RAG over ai_core.",
        "requires": ["ai_core", "embeddings", "vector_store", "rag"],
    },
    "agent_stack": {
        "description": "Tool-using agents with streaming and evaluation.",
        "requires": ["ai_core", "tool_calling", "streaming", "eval_harness"],
    },
    "realtime_core": {
        "description": "Live updates: SSE and websocket transport.",
        "requires": ["sse_stream", "websocket_manager"],
    },
    "observability_core": {
        "description": "Know what's happening in prod: structured logs, metrics, tracing, error reporting.",
        "requires": ["structured_logging", "metrics", "tracing", "error_reporting"],
    },
    "analytics_core": {
        "description": "Product analytics: event tracking, funnels, usage metrics, reports.",
        "requires": ["event_tracking", "funnels", "usage_metrics", "reports"],
    },
    "frontend_app": {
        "description": "Shipped UI surface: navbars, tables, forms, dashboards, settings, empty states.",
        "requires": ["navbars", "tables", "forms", "frontend.dashboards",
                     "settings_pages", "empty_states"],
    },
    "frontend_marketing": {
        "description": "Public-facing pages: pricing, auth pages, forms.",
        "requires": ["pricing_pages", "auth_pages", "forms"],
    },
    "deploy_container": {
        "description": "Ship it: docker, CI, health probe, backups.",
        "requires": ["docker", "github_actions", "healthcheck_probe", "backups"],
    },
}


def load_catalog() -> dict:
    with open(CAT, encoding="utf-8") as f:
        return json.load(f)


def build_concrete(cat: dict):
    """Map every part to a concrete capability name; qualify collisions."""
    by_name: dict[str, list[dict]] = {}
    for layer, parts in cat["layers"].items():
        for p in parts:
            p = {**p, "_layer": layer}
            by_name.setdefault(p["name"], []).append(p)

    concrete: dict[str, dict] = {}
    collisions: list[str] = []
    name_to_cap: dict[tuple, str] = {}  # (layer, name) -> capability key
    for name, plist in by_name.items():
        if len(plist) == 1:
            p = plist[0]
            cap = name
            concrete[cap] = {
                "part": p["import_path"], "layer": p["_layer"],
                "status": p["status"], "addition": p.get("addition", False),
                "purpose": p["purpose"], "requires": [],
            }
            name_to_cap[(p["_layer"], name)] = cap
        else:
            collisions.append(name)
            for p in plist:
                cap = f"{p['_layer']}.{name}"
                concrete[cap] = {
                    "part": p["import_path"], "layer": p["_layer"],
                    "status": p["status"], "addition": p.get("addition", False),
                    "purpose": p["purpose"], "requires": [],
                }
                name_to_cap[(p["_layer"], name)] = cap
    return concrete, collisions, name_to_cap


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    cat = load_catalog()
    concrete, collisions, _ = build_concrete(cat)

    # Attach authored concrete->concrete requires.
    errors: list[str] = []
    all_caps = set(concrete) | set(META)
    for cap, reqs in PART_REQUIRES.items():
        if cap not in concrete:
            errors.append(f"PART_REQUIRES references unknown capability '{cap}'")
            continue
        for r in reqs:
            if r not in all_caps:
                errors.append(f"'{cap}' requires unknown capability '{r}'")
        concrete[cap]["requires"] = reqs

    # Validate meta edges.
    for m, spec in META.items():
        for r in spec["requires"]:
            if r not in all_caps:
                errors.append(f"meta '{m}' requires unknown capability '{r}'")

    if errors:
        print("GRAPH VALIDATION FAILED:")
        for e in errors:
            print("  - " + e)
        return 1

    core = sum(1 for c in concrete.values() if c["status"] == "core")
    payload = {
        "schema": "scrapyard/capabilities@1",
        "totals": {
            "concrete": len(concrete), "meta": len(META),
            "concrete_core": core, "collisions_qualified": collisions,
            "edges": sum(len(c["requires"]) for c in concrete.values())
                     + sum(len(m["requires"]) for m in META.values()),
        },
        "concrete": dict(sorted(concrete.items())),
        "meta": dict(sorted(META.items())),
    }

    print(f"graph OK: {len(concrete)} concrete ({core} core), {len(META)} meta, "
          f"{payload['totals']['edges']} edges"
          + (f", qualified collisions: {collisions}" if collisions else ""))
    if check_only:
        return 0
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"wrote {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
