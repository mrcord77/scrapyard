# Capabilities — documentation_site + iep_binder
_Generated honestly from the assembled plan. Lists what actually runs, what production requires, and which local-only fallbacks ship by default._

## Included parts (31)

`account_deletion`, `app_factory`, `audit_logs`, `auth_pages`, `base_model`, `cms`, `config`, `data_export`, `error_handling`, `error_taxonomy`, `field_encryption`, `filters`, `forms`, `full_text_search`, `health`, `logging_setup`, `markdown_pages`, `middleware`, `pagination_params`, `pricing_pages`, `privacy_policy_hooks`, `request_context`, `retention_policy`, `routers`, `search_pagination`, `seo_metadata`, `settings_validation`, `sitemap`, `sorting`, `users`, `validation`

## Runnable endpoints

- `GET /healthz`, `GET /livez` — health/liveness
- `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- `GET|POST /children`, `GET|PUT|DELETE /children/{id}` — Child CRUD (auth + owner-scoped)
- `GET|POST /meetings`, `GET|PUT|DELETE /meetings/{id}` — Meeting CRUD (auth + owner-scoped)
- `GET|POST /correspondences`, `GET|PUT|DELETE /correspondences/{id}` — Correspondence CRUD (auth + owner-scoped)
- `GET|POST /service_entries`, `GET|PUT|DELETE /service_entries/{id}` — ServiceEntry CRUD (auth + owner-scoped)
- `GET|POST /action_items`, `GET|PUT|DELETE /action_items/{id}` — ActionItem CRUD (auth + owner-scoped)
- `GET /app/` — generated single-page frontend

## Required configuration

| Variable | When | Notes |
|---|---|---|
| `DATABASE_URL` | required (non-dev) | Postgres/MySQL URL; dev falls back to local sqlite |
| `AUDIT_WITNESS_PUBLIC / AUDIT_WITNESS_SECRET` | recommended | stable audit witness key for cross-restart tamper-evidence |

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