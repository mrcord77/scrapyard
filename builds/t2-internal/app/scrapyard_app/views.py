"""Generated views — server-rendered dashboard using Jinja2 + Tailwind."""
from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def register_views(app: FastAPI, templates: Jinja2Templates):
    """Mount the server-rendered dashboard at /."""

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        stats = []
        items = []
        health_checks = [{"label": "API", "ok": True}]
        routes = []

        # Pull live stats from the backend
        try:
            from scrapyard.database.db_session import get_db
            db = next(get_db())
            try:
                from scrapyard.admin.dashboards import admin_overview
                overview = admin_overview(db)
                for k, v in overview.items():
                    stats.append({"label": k.replace("_", " ").title(), "value": v})
            except Exception:
                pass
            db.close()
        except Exception:
            health_checks.append({"label": "Database", "ok": False})

        # Capabilities / mounted routes
        try:
            from scrapyard_app.capabilities import CAPABILITIES
            routes = CAPABILITIES.get("routers_mounted", [])
            if not stats:
                stats.append({"label": "Feature Routes", "value": len(routes)})
        except Exception:
            pass

        if not stats:
            stats = [{"label": "Status", "value": "Running"}]

        return templates.TemplateResponse(request, "dashboard.html", {
            "title": "Dashboard",
            "stats": stats, "items": items,
            "health_checks": health_checks, "routes": routes,
        })

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        return templates.TemplateResponse(request, "error.html", {
            "title": "Page not found",
            "message": "The page you are looking for does not exist.",
        }, status_code=404)

    @app.exception_handler(500)
    async def server_error(request: Request, exc):
        return templates.TemplateResponse(request, "error.html", {
            "title": "Something went wrong",
            "message": "An unexpected error occurred. Please try again.",
        }, status_code=500)
