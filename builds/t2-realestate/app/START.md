# directory_site+real_estate — assembled app

Browseable directory/listing site with faceted filters and saved searches.

Domain: **Property listings / brokerage**. See DOMAIN.md for entities/workflows to scaffold.

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
- `scrapyard.content.seo_metadata`
- `scrapyard.content.sitemap`
- `scrapyard.identity.auth_routes`
- `scrapyard.identity.users`
- `scrapyard.identity.password_hashing`
- `scrapyard.identity.jwt_manager`
- `scrapyard.identity.session_manager`

## Verified status of copied parts
- 27 of 27 copied parts are verified core (metadata present, imports OK, no hollow NotImplementedError) per tools/index_catalog.py.

## Next
1. `pip install -r requirements.txt`
2. Run the app: `DATABASE_URL=sqlite:///./app.db uvicorn main:app --reload`
