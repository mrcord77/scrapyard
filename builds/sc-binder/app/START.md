# documentation_site+iep_binder — assembled app

Versioned docs: markdown pages, navigation, SEO, search.

Domain: **The Binder**. See DOMAIN.md for entities/workflows to scaffold.

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
- `scrapyard.content.cms`
- `scrapyard.content.markdown_pages`
- `scrapyard.content.seo_metadata`
- `scrapyard.content.sitemap`
- `scrapyard.search.full_text_search`
- `scrapyard.search.filters`
- `scrapyard.search.sorting`
- `scrapyard.search.search_pagination`
- `scrapyard.frontend.pricing_pages`
- `scrapyard.frontend.forms`
- `scrapyard.frontend.auth_pages`
- `scrapyard.security.field_encryption`
- `scrapyard.compliance.account_deletion`
- `scrapyard.identity.users`
- `scrapyard.compliance.data_export`
- `scrapyard.admin.audit_logs`
- `scrapyard.database.base_model`
- `scrapyard.compliance.retention_policy`
- `scrapyard.compliance.privacy_policy_hooks`
- `scrapyard.identity.auth_routes`
- `scrapyard.identity.password_hashing`
- `scrapyard.identity.jwt_manager`
- `scrapyard.identity.session_manager`
- `scrapyard.security.crypto_agility`
- `scrapyard.security.pq_envelope`
- `scrapyard.security.pq_field_encryption`
- `scrapyard.security.pq_signing`

## Verified status of copied parts
- 39 of 39 copied parts are verified core (metadata present, imports OK, no hollow NotImplementedError) per tools/index_catalog.py.

## Next
1. `pip install -r requirements.txt`
2. Run the app: `DATABASE_URL=sqlite:///./app.db uvicorn main:app --reload`
