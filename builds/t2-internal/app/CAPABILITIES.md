# Capabilities — internal_tool

_Generated. Lists what runs, what production needs, and local-only fallbacks._

## Always-on endpoints
- `GET /health`
- `GET /capabilities`

## Mounted feature routers
- `/admin` (scrapyard.admin.admin_routes)

## Required configuration (see .env.example)
- `AUDIT_WITNESS_PUBLIC` ← scrapyard.admin.audit_logs
- `AUDIT_WITNESS_SECRET` ← scrapyard.admin.audit_logs
- `JWT_SECRET` ← scrapyard.identity.jwt_manager

## Local-only fallbacks (refused in production)
- security.local_crypto_backend → `SCRAPYARD_CRYPTO_BACKEND=citadel`
- communication.email_console → configure SMTP
- ai.offline_provider → set `SCRAPYARD_LLM_PROVIDER` + key
- jobs.memory_queue → `JOBS_BACKEND=db`

## Honest status
- `production_ready: false` — configure the above and run migrations before production.
- Routers that can't wire are skipped in dev (see `/capabilities`) and **raise** in production.