# Capabilities — web_application + bikeshop
_Generated honestly from the assembled plan. Lists what actually runs, what production requires, and which local-only fallbacks ship by default._

## Included parts (25)

`app_factory`, `base_model`, `config`, `cors`, `db_session`, `error_handling`, `error_taxonomy`, `health`, `input_sanitization`, `logging_setup`, `middleware`, `migrations`, `pagination`, `pagination_params`, `rate_limiting`, `repository`, `request_context`, `routers`, `secrets`, `security_headers`, `settings_validation`, `soft_delete`, `timestamps`, `transactions`, `validation`

## Runnable endpoints

- `GET /healthz`, `GET /livez` — health/liveness
- `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- `GET|POST /users`, `GET|PUT|DELETE /users/{id}` — User CRUD (PUBLIC — no auth (low-sensitivity tier))
- `GET|POST /repair_tickets`, `GET|PUT|DELETE /repair_tickets/{id}` — RepairTicket CRUD (reads auth-only; writes require role 'admin')
- `GET /app/` — generated single-page frontend

## Required configuration

| Variable | When | Notes |
|---|---|---|
| `DATABASE_URL` | required (non-dev) | Postgres/MySQL URL; dev falls back to local sqlite |

## Local-only fallbacks (refused in production)

These ship active by default for dev/test; `bootstrap()` refuses to start with `APP_ENV=production` while any are live, so they can never run silently in prod:

- **security.local_crypto_backend** — reference-impl ML-KEM/ML-DSA. Disable: `SCRAPYARD_CRYPTO_BACKEND=citadel`.
- **communication.email_console** — email logged, not sent. Disable: configure `SMTP_HOST`/`SMTP_URL`/`EMAIL_PROVIDER`.
- **ai.offline_provider** — AI calls use an offline stub. Disable: set `SCRAPYARD_LLM_PROVIDER` + provider key.

## Local-only (warned, not blocked)

- **audit.ephemeral_witness_key** — process-generated witness key (not durable across restarts). Set `AUDIT_WITNESS_PUBLIC/SECRET` for durable evidence.

## Honest limits

- Generated CRUD is generic (no product-specific business logic yet).
- Tables auto-create in dev; use migrations for production schema management.
- Reference-impl PQ crypto is not FIPS/CMVP-validated — citadel or a validated backend closes that.