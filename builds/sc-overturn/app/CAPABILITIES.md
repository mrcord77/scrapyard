# Capabilities — saas_subscription_app + appeal_fighter
_Generated honestly from the assembled plan. Lists what actually runs, what production requires, and which local-only fallbacks ship by default._

## Included parts (70)

`account_deletion`, `account_lockout`, `admin_access`, `app_factory`, `audit_logs`, `auth_pages`, `auth_routes`, `backups`, `base_model`, `cancellation_flow`, `config`, `cors`, `data_export`, `db_session`, `docker`, `email`, `email_verification`, `empty_states`, `entitlement_gate`, `entitlements`, `error_handling`, `error_taxonomy`, `field_encryption`, `forms`, `frontend.dashboards`, `github_actions`, `health`, `healthcheck_probe`, `input_sanitization`, `invoices`, `jwt_manager`, `logging_setup`, `middleware`, `migrations`, `navbars`, `notification_center`, `pagination`, `pagination_params`, `password_hashing`, `password_policy`, `password_reset`, `permissions`, `pricing_pages`, `privacy_policy_hooks`, `rate_limiting`, `repository`, `request_context`, `retention_policy`, `roles`, `routers`, `sales_tax_filing_calendar`, `sales_tax_nexus`, `secrets`, `security_headers`, `session_manager`, `settings_pages`, `settings_validation`, `soft_delete`, `stripe_checkout`, `stripe_tax`, `stripe_webhooks`, `subscription_status`, `subscriptions`, `tables`, `templates`, `timestamps`, `transactions`, `unsubscribe_handling`, `users`, `validation`

## Runnable endpoints

- `GET /healthz`, `GET /livez` — health/liveness
- `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- `GET|POST /claims`, `GET|PUT|DELETE /claims/{id}` — Claim CRUD (auth + owner-scoped)
- `GET|POST /denials`, `GET|PUT|DELETE /denials/{id}` — Denial CRUD (auth + owner-scoped)
- `GET|POST /appeals`, `GET|PUT|DELETE /appeals/{id}` — Appeal CRUD (auth + owner-scoped)
- `GET|POST /evidence_items`, `GET|PUT|DELETE /evidence_items/{id}` — EvidenceItem CRUD (auth + owner-scoped)
- `GET|POST /call_logs`, `GET|PUT|DELETE /call_logs/{id}` — CallLog CRUD (auth + owner-scoped)
- `GET /app/` — generated single-page frontend

## Required configuration

| Variable | When | Notes |
|---|---|---|
| `DATABASE_URL` | required (non-dev) | Postgres/MySQL URL; dev falls back to local sqlite |
| `AUDIT_WITNESS_PUBLIC / AUDIT_WITNESS_SECRET` | recommended | stable audit witness key for cross-restart tamper-evidence |
| `STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET` | required for billing | real Stripe credentials |
| `SMTP_HOST / SMTP_URL / EMAIL_PROVIDER` | required in prod | without it, email logs to console instead of sending |

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