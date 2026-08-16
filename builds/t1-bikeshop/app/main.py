"""Generated application entrypoint. Boots with: uvicorn main:app"""
import os
from scrapyard.runtime.startup import bootstrap
from scrapyard.models.models import Base
from scrapyard.models.routes import router as models_router
from scrapyard.database.db_session import get_db
from scrapyard.identity.auth_routes import build_auth_router
from fastapi.staticfiles import StaticFiles

app = bootstrap(
    routers=[models_router, build_auth_router(get_db)],
    models_base=Base,
    require_encryption=False,
    security_caps=['roles', 'session_manager', 'users'],
)

# serve the generated single-page frontend at /app (talks to the API above)
_fe = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend')
if os.path.isdir(_fe):
    app.mount('/app', StaticFiles(directory=_fe, html=True), name='frontend')

# run:  DATABASE_URL=... uvicorn main:app --reload   ->  UI at /app
