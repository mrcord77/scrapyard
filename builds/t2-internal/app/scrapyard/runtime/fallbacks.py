"""Runtime fallback registry — make local-only behavior honest and fail-closed.

Many parts have a convenient local/offline path (reference-implementation PQ crypto,
console email, in-memory queue/vector store, offline LLM). Those are fine for dev
and tests, dangerous if they run silently in production. This registry lets the
active fallbacks be *named*, surfaced in CAPABILITIES.md, and — in production —
refused at startup so a build can never quietly run a non-production path.

Detection is config-resolvable: detect_fallbacks(settings) inspects the environment
at boot and registers whichever fallbacks are actually active, then bootstrap calls
assert_no_forbidden_fallbacks(app_env).

### PART-META-JSON
{
  "name": "fallbacks",
  "layer": "runtime",
  "purpose": "Runtime fallback registry: name every local-only/dev path that is actually active (reference crypto, console email, offline LLM, in-memory queue/cache/rate-limit, non-Postgres RLS, ephemeral audit key, missing telemetry) via env/config detection, and refuse production startup while any forbidden fallback is live.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Environment variables and an optional settings object (database_url) at boot.",
  "outputs": "A registry of active fallbacks; a hard RuntimeError in production when forbidden ones are active.",
  "files_created": [],
  "security_notes": "This is a fail-closed production gate: assert_no_forbidden_fallbacks raises in production if reference-implementation crypto, console email, an offline LLM, per-process rate limiting/caching, or unenforced RLS is active, so dev conveniences can never silently serve production traffic. Detection reads env vars only — it cannot prove a backend works, only that one is configured. Conscious opt-outs (SCRAPYARD_RLS=off etc.) are explicit and named in the registry.",
  "ai_usage": "detect_fallbacks(settings) at boot, then assert_no_forbidden_fallbacks(settings.app_env); read active() for CAPABILITIES reporting.",
  "example": "detect_fallbacks(settings); assert_no_forbidden_fallbacks(settings.app_env)",
  "import_path": "scrapyard.runtime.fallbacks"
}
### END-PART-META
"""
from __future__ import annotations
import os

STATUS = "core"

# name -> {"detail": str, "forbidden_in_prod": bool}
_REGISTRY: dict[str, dict] = {}


def register_fallback(name: str, detail: str, *, forbidden_in_prod: bool = True) -> None:
    """Record that a local-only path is active. Idempotent by name."""
    _REGISTRY[name] = {"detail": detail, "forbidden_in_prod": forbidden_in_prod}


def clear() -> None:
    _REGISTRY.clear()


def active() -> dict[str, dict]:
    return dict(_REGISTRY)


def forbidden_active() -> list[str]:
    return sorted(n for n, v in _REGISTRY.items() if v["forbidden_in_prod"])


def detect_fallbacks(settings=None) -> dict[str, dict]:
    """Inspect env/config and register the fallbacks that are actually active.
    Called at startup before the production gate. Re-runnable (clears first)."""
    clear()

    # Crypto: the in-process backend is a correct FIPS reference implementation,
    # not constant-time/audited — not for production. citadel is the prod backend.
    backend = os.environ.get("SCRAPYARD_CRYPTO_BACKEND", "local").strip().lower()
    if backend != "citadel":
        register_fallback(
            "security.local_crypto_backend",
            "reference-implementation ML-KEM/ML-DSA (not constant-time/audited); "
            "set SCRAPYARD_CRYPTO_BACKEND=citadel for the production primitive",
            forbidden_in_prod=True,
        )

    # Email: with no SMTP transport configured, sends go to console/outbox.
    if not (os.environ.get("SMTP_HOST") or os.environ.get("SMTP_URL") or os.environ.get("EMAIL_PROVIDER")):
        register_fallback(
            "communication.email_console",
            "no SMTP/email provider configured; messages are logged, not delivered "
            "(set SMTP_HOST/SMTP_URL or EMAIL_PROVIDER)",
            forbidden_in_prod=True,
        )

    # LLM: an offline/echo provider must never serve production traffic.
    provider = os.environ.get("SCRAPYARD_LLM_PROVIDER", "").strip().lower()
    has_key = any(os.environ.get(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"))
    if provider in ("offline", "echo") or (provider == "" and not has_key):
        register_fallback(
            "ai.offline_provider",
            "no real LLM provider configured; AI calls use an offline/echo stub "
            "(set SCRAPYARD_LLM_PROVIDER + the provider API key)",
            forbidden_in_prod=True,
        )

    # Jobs: the in-memory queue loses work on restart and can't share across
    # workers — production needs the durable DB-backed queue.
    if os.environ.get("JOBS_BACKEND", "memory").strip().lower() != "db":
        register_fallback(
            "jobs.memory_queue",
            "in-memory job queue (work lost on restart, no multi-worker safety); "
            "set JOBS_BACKEND=db to use the durable db_queue",
            forbidden_in_prod=True,
        )

    # Audit witness: an auto-generated (non-persisted) key is verifiable only within
    # one process — durable cross-restart evidence needs a stable key. Surfaced as a
    # warning rather than a hard block (the chain still protects within a run).
    if not (os.environ.get("AUDIT_WITNESS_PUBLIC") and os.environ.get("AUDIT_WITNESS_SECRET")):
        register_fallback(
            "audit.ephemeral_witness_key",
            "audit witness key is process-generated (not durable across restarts); "
            "set AUDIT_WITNESS_PUBLIC/SECRET or use citadel custody",
            forbidden_in_prod=False,
        )

    # Row-level security is enforced only on PostgreSQL. A non-Postgres production
    # database means cross-tenant/owner isolation is NOT enforced at the database.
    db_url = ((getattr(settings, "database_url", "") if settings else "")
              or os.environ.get("DATABASE_URL", "")).strip().lower()
    if (db_url and not db_url.startswith("postgres")
            and os.environ.get("SCRAPYARD_RLS", "require").strip().lower() != "off"):
        register_fallback(
            "security.rls_unenforced",
            "row-level security is enforced only on PostgreSQL; this app is configured "
            "with a non-Postgres database, so per-tenant/per-owner isolation is NOT "
            "enforced at the database (use a PostgreSQL DATABASE_URL, or set "
            "SCRAPYARD_RLS=off to consciously accept app-level-only scoping)",
            forbidden_in_prod=True,
        )

    # Cache: the in-memory cache is per-process (lost on restart, not shared across
    # workers/instances) — production needs Redis. Conscious opt-out: SCRAPYARD_CACHE=off.
    if (os.environ.get("CACHE_BACKEND", "memory").strip().lower() != "redis"
            and os.environ.get("SCRAPYARD_CACHE", "require").strip().lower() != "off"):
        register_fallback(
            "caching.memory_cache",
            "in-memory cache (per-process, lost on restart, not shared across workers); "
            "set CACHE_BACKEND=redis + REDIS_URL, or SCRAPYARD_CACHE=off if this app "
            "does not rely on a shared cache",
            forbidden_in_prod=True,
        )

    # Rate limiting: an in-memory limiter holds state per process, so N instances each
    # admit the full limit (~N x the intended rate). Production needs the Redis limiter.
    if (os.environ.get("RATE_LIMIT_BACKEND", "memory").strip().lower() != "redis"
            and os.environ.get("SCRAPYARD_RATELIMIT", "require").strip().lower() != "off"):
        register_fallback(
            "security.memory_rate_limit",
            "per-process rate limiter (each worker/instance admits the full limit, so the "
            "global rate is ~N x intended); set RATE_LIMIT_BACKEND=redis + REDIS_URL, or "
            "SCRAPYARD_RATELIMIT=off if this app does not enforce rate limits",
            forbidden_in_prod=True,
        )

    # Observability: a production build should not run silently unobserved. If no
    # error-tracking/tracing exporter is configured, surface it (warning, not a hard
    # block — missing telemetry degrades insight, it isn't a security hole).
    if not (os.environ.get("SENTRY_DSN") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")):
        register_fallback(
            "observability.no_error_tracking",
            "no error-tracking/tracing exporter configured (set SENTRY_DSN and/or "
            "OTEL_EXPORTER_OTLP_ENDPOINT); the app runs but errors and traces are not exported",
            forbidden_in_prod=False,
        )

    return active()


def assert_no_forbidden_fallbacks(app_env: str) -> None:
    """In production, refuse to start if any forbidden local-only path is active.
    A build must never silently run reference crypto, console email, or an offline
    LLM in production. No-op outside production."""
    if app_env != "production":
        return
    bad = forbidden_active()
    if bad:
        lines = "\n".join(f"  - {n}: {_REGISTRY[n]['detail']}" for n in bad)
        raise RuntimeError(
            "refusing to start in production with local-only fallbacks active:\n"
            + lines
            + "\nConfigure the production backends, or run with APP_ENV=development."
        )


def _selftest() -> None:
    _RELEVANT = ("SCRAPYARD_CRYPTO_BACKEND", "SMTP_HOST", "SMTP_URL", "EMAIL_PROVIDER",
                 "SCRAPYARD_LLM_PROVIDER", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                 "JOBS_BACKEND", "AUDIT_WITNESS_PUBLIC", "AUDIT_WITNESS_SECRET",
                 "DATABASE_URL", "SCRAPYARD_RLS", "CACHE_BACKEND", "SCRAPYARD_CACHE",
                 "RATE_LIMIT_BACKEND", "SCRAPYARD_RATELIMIT", "SENTRY_DSN",
                 "OTEL_EXPORTER_OTLP_ENDPOINT")
    saved = {k: os.environ.get(k) for k in _RELEVANT}
    try:
        for k in _RELEVANT:
            os.environ.pop(k, None)

        # registry basics
        clear()
        register_fallback("x.demo", "demo path", forbidden_in_prod=True)
        register_fallback("x.warn", "warn-only path", forbidden_in_prod=False)
        assert set(active()) == {"x.demo", "x.warn"}
        assert forbidden_active() == ["x.demo"]

        # bare env: the known dev fallbacks are detected
        found = detect_fallbacks()
        assert "security.local_crypto_backend" in found
        assert "communication.email_console" in found
        assert "ai.offline_provider" in found
        assert "jobs.memory_queue" in found
        # sqlite DATABASE_URL triggers the RLS fallback
        os.environ["DATABASE_URL"] = "sqlite:///./app.db"
        assert "security.rls_unenforced" in detect_fallbacks()

        # production refuses to start; development does not
        try:
            assert_no_forbidden_fallbacks("production")
            raise AssertionError("prod started with forbidden fallbacks")
        except RuntimeError as e:
            assert "refusing to start" in str(e)
        assert_no_forbidden_fallbacks("development")  # no-op

        # fully configured env: only warning-grade fallbacks remain
        os.environ.update({
            "SCRAPYARD_CRYPTO_BACKEND": "citadel",
            "SMTP_HOST": "smtp.example.test",
            "SCRAPYARD_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "test-key",
            "JOBS_BACKEND": "db",
            "DATABASE_URL": "postgresql://db.example.test/app",
            "CACHE_BACKEND": "redis",
            "RATE_LIMIT_BACKEND": "redis",
        })
        found = detect_fallbacks()
        assert forbidden_active() == [], f"unexpected forbidden fallbacks: {forbidden_active()}"
        # warnings (ephemeral witness key, no telemetry) may remain but do not block
        assert_no_forbidden_fallbacks("production")

        # settings.database_url is honoured over env
        class _S:
            database_url = "sqlite:///./tenant.db"
        os.environ.pop("SCRAPYARD_RLS", None)
        assert "security.rls_unenforced" in detect_fallbacks(_S())
        # conscious opt-out clears it
        os.environ["SCRAPYARD_RLS"] = "off"
        assert "security.rls_unenforced" not in detect_fallbacks(_S())
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        clear()

    print("fallbacks selftest: PASS")


if __name__ == "__main__":
    _selftest()
