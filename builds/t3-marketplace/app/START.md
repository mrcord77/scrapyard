# marketplace+ecommerce — assembled app

Two-sided marketplace: listings, faceted search, payments, moderation, reviews.

Domain: **Online retail / storefront**. See DOMAIN.md for entities/workflows to scaffold.

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
- `scrapyard.frontend.navbars`
- `scrapyard.frontend.tables`
- `scrapyard.frontend.forms`
- `scrapyard.frontend.dashboards`
- `scrapyard.frontend.settings_pages`
- `scrapyard.frontend.empty_states`

## Verified status of copied parts
- 52 of 52 copied parts are verified core (metadata present, imports OK, no hollow NotImplementedError) per tools/index_catalog.py.

## Next
1. `pip install -r requirements.txt`
2. Run the app: `DATABASE_URL=sqlite:///./app.db uvicorn main:app --reload`
