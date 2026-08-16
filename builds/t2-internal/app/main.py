"""Generated entrypoint. Boot with: uvicorn main:app --reload"""
import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from scrapyard.api.app_factory import create_app
from scrapyard_app.bootstrap import startup_checks
from scrapyard_app.routes import include_routes
from scrapyard_app.settings import settings

startup_checks()                       # validate config, init DB, gate prod fallbacks
app = create_app(title="Scrapyard Generated App")

# Request-level enforcement on EVERY route (zero per-route wiring). PrincipalMiddleware
# is added last so it runs first/outermost (resolves the caller), then RateLimitMiddleware
# keys its global limit on that principal. Both degrade safely without their backends.
try:
    from scrapyard.runtime.request_security import PrincipalMiddleware, RateLimitMiddleware
    from scrapyard.security.rate_limiting import get_rate_limiter
    app.add_middleware(RateLimitMiddleware, limiter_factory=get_rate_limiter)
    app.add_middleware(PrincipalMiddleware, jwt_secret=settings.secret_key)
except Exception as _e:
    print(f"[bootstrap] request-security middleware not enabled: {_e}")

include_routes(app)                    # /health, /capabilities, + selected routers

# Server-rendered frontend: Jinja2 + Tailwind CDN
_tpl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
if os.path.isdir(_tpl_dir):
    templates = Jinja2Templates(directory=_tpl_dir)
    from scrapyard_app.views import register_views
    register_views(app, templates)
