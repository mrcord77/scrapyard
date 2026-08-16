# saas_subscription_app+healthcare — assembled app

Multi-tenant subscription SaaS: auth, RBAC, Stripe billing, admin, the works.

Domain: **Health / clinical (NON-clinical-decision; admin & scheduling focus)**. See DOMAIN.md for entities/workflows to scaffold.

## Included parts
- `scrapyard.foundation.config`
- `scrapyard.foundation.logging_setup`
- `scrapyard.foundation.health`
- `scrapyard.foundation.error_taxonomy`
- `scrapyard.foundation.settings_validation`
- `scrapyard.api.app_factory`
- `scrapyard.api.request_context`
- `scrapyard.api.error_handling`
- `scrapyard.api.routers`
- `scrapyard.api.validation`
- `scrapyard.api.pagination_params`
- `scrapyard.api.middleware`
- `scrapyard.database.db_session`
- `scrapyard.database.base_model`
- `scrapyard.database.timestamps`
- `scrapyard.database.soft_delete`
- `scrapyard.database.pagination`
- `scrapyard.database.repository`
- `scrapyard.database.transactions`
- `scrapyard.database.migrations`
- `scrapyard.security.security_headers`
- `scrapyard.security.cors`
- `scrapyard.security.rate_limiting`
- `scrapyard.security.input_sanitization`
- `scrapyard.security.secrets`
- `scrapyard.identity.users`
- `scrapyard.identity.password_hashing`
- `scrapyard.security.password_policy`
- `scrapyard.identity.jwt_manager`
- `scrapyard.identity.session_manager`
- `scrapyard.identity.auth_routes`
- `scrapyard.identity.email_verification`
- `scrapyard.communication.email`
- `scrapyard.identity.password_reset`
- `scrapyard.identity.account_lockout`
- `scrapyard.frontend.navbars`
- `scrapyard.frontend.tables`
- `scrapyard.frontend.forms`
- `scrapyard.frontend.dashboards`
- `scrapyard.frontend.settings_pages`
- `scrapyard.frontend.empty_states`
- `scrapyard.authorization.roles`
- `scrapyard.authorization.permissions`
- `scrapyard.authorization.admin_access`
- `scrapyard.billing.subscriptions`
- `scrapyard.billing.subscription_status`
- `scrapyard.billing.stripe_checkout`
- `scrapyard.billing.stripe_webhooks`
- `scrapyard.billing.invoices`
- `scrapyard.billing.cancellation_flow`
- `scrapyard.billing.entitlements`
- `scrapyard.authorization.entitlement_gate`
- `scrapyard.compliance.sales_tax_nexus`
- `scrapyard.billing.stripe_tax`
- `scrapyard.compliance.sales_tax_filing_calendar`
- `scrapyard.communication.templates`
- `scrapyard.communication.notification_center`
- `scrapyard.communication.unsubscribe_handling`
- `scrapyard.frontend.pricing_pages`
- `scrapyard.frontend.auth_pages`
- `scrapyard.deployment.docker`
- `scrapyard.deployment.github_actions`
- `scrapyard.deployment.healthcheck_probe`
- `scrapyard.deployment.backups`
- `scrapyard.security.pq_field_encryption`
- `scrapyard.security.pq_envelope`
- `scrapyard.security.crypto_agility`
- `scrapyard.security.field_encryption`
- `scrapyard.compliance.account_deletion`
- `scrapyard.compliance.data_export`
- `scrapyard.admin.audit_logs`
- `scrapyard.compliance.retention_policy`
- `scrapyard.compliance.privacy_policy_hooks`
- `scrapyard.security.pq_signing`

## Verified status of copied parts
- 74 of 74 copied parts are verified core (metadata present, imports OK, no hollow NotImplementedError) per tools/index_catalog.py.

## Next
1. `pip install -r requirements.txt`
2. Run the app: `DATABASE_URL=sqlite:///./app.db uvicorn main:app --reload`
