# internal_tool — assembled app

Internal admin tool: simple auth, tables, audit logs, RBAC.

Dependency closure resolved — the copied set is import-complete.

## Included parts
- `scrapyard.admin.admin_routes`
- `scrapyard.admin.audit_logs`
- `scrapyard.admin.dashboards`
- `scrapyard.admin.impersonation`
- `scrapyard.admin.user_management`
- `scrapyard.analytics.usage_metrics`
- `scrapyard.api.app_factory`
- `scrapyard.api.error_handling`
- `scrapyard.api.request_context`
- `scrapyard.authorization.admin_access`
- `scrapyard.authorization.permissions`
- `scrapyard.authorization.roles`
- `scrapyard.database.base_model`
- `scrapyard.database.db_session`
- `scrapyard.database.pagination`
- `scrapyard.database.repository`
- `scrapyard.database.timestamps`
- `scrapyard.foundation.config`
- `scrapyard.foundation.error_taxonomy`
- `scrapyard.foundation.health`
- `scrapyard.foundation.logging_setup`
- `scrapyard.frontend.forms`
- `scrapyard.frontend.tables`
- `scrapyard.identity.jwt_manager`
- `scrapyard.identity.password_hashing`
- `scrapyard.identity.session_manager`
- `scrapyard.identity.users`
- `scrapyard.security.rate_limiting`
- `scrapyard.security.security_headers`

## Verified status of copied parts
- 29 of 29 copied parts are verified core (metadata present, imports OK, no hollow NotImplementedError) per tools/index_catalog.py.

## Next
1. `pip install -r requirements.txt`
2. Run the app: `DATABASE_URL=sqlite:///./app.db uvicorn main:app --reload`
