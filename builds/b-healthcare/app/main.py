"""Generated application entrypoint. Boots with: uvicorn main:app"""
import os
from scrapyard.runtime.startup import bootstrap
from scrapyard.models.models import Base
from scrapyard.models.routes import router as models_router
from scrapyard.database.db_session import get_db
from scrapyard.identity.auth_routes import build_auth_router
from fastapi.staticfiles import StaticFiles

from scrapyard.runtime.lifespan import Hooks
from scrapyard.database.db_session import session_scope
from scrapyard.models.retention import run_retention
_hooks = Hooks()

@_hooks.on_startup
def _retention_sweep():
    with session_scope() as _db:
        run_retention(_db)

app = bootstrap(
    routers=[models_router, build_auth_router(get_db)],
    models_base=Base,
    require_encryption=True,
    security_caps=['account_deletion', 'audit_logs', 'session_manager', 'users'],
    hooks=_hooks,
)

# serve the generated single-page frontend at /app (talks to the API above)
_fe = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend')
if os.path.isdir(_fe):
    app.mount('/app', StaticFiles(directory=_fe, html=True), name='frontend')

# run:  DATABASE_URL=... PQ_FIELD_PUBLIC=... PQ_FIELD_SECRET=... uvicorn main:app --reload   ->  UI at /app
