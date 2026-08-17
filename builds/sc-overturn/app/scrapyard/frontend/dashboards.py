"""
dashboards — Dashboard shell with cards/charts slots.

### PART-META-JSON
{
  "name": "dashboards",
  "layer": "frontend",
  "purpose": "Python/jinja2 server-side HTML rendering of dashboard shells with card/chart slots, plus FastAPI HTMLResponse and SQLAlchemy-backed data helpers (no react).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi",
    "jinja2",
    "sqlalchemy"
  ],
  "inputs": "Public API: render_card(title, content, classes); render_chart(chart_id, chart_type, data); render_with_layout(content, layout); escape_and_render(text); render_error_dashboard(title, error); ConfigError(...); SecurityError(...); DashboardModel(...) (plus more).",
  "outputs": "Returns: render_card -> str; render_chart -> str; render_with_layout -> str; escape_and_render -> str; render_error_dashboard -> str.",
  "files_created": [],
  "security_notes": "Card titles/values are escaped; chart payloads are serialized data only. Do not embed secrets in dashboard context - rendered HTML is client-visible.",
  "ai_usage": "Import `render_card` from `scrapyard.frontend.dashboards` and call it as shown in `example`; run `py -m scrapyard.frontend.dashboards` to see its offline selftest.",
  "example": "from scrapyard.frontend.dashboards import render_card",
  "import_path": "scrapyard.frontend.dashboards"
}
### END-PART-META
"""
from __future__ import annotations
import html
from typing import Dict, Optional, Union
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select
from jinja2 import Template

STATUS = "core"

class ConfigError(Exception):
    pass

class SecurityError(Exception):
    pass

def render_card(title: str, content: str, classes: str = "card") -> str:
    return f'<div class="{classes}"><h2>{html.escape(title)}</h2><p>{html.escape(content)}</p></div>'

def render_chart(chart_id: str, chart_type: str, data: Dict[str, Union[int, float]]) -> str:
    if chart_type not in ["bar", "line", "pie"]:
        raise ValueError(f"Unsupported chart type: {chart_type}")
    
    return f'<div id="{html.escape(chart_id)}" class="chart-{chart_type}">{html.escape(str(data))}</div>'

def render_with_layout(content: str, layout: str = "grid") -> str:
    if layout not in ["grid", "flex"]:
        raise ValueError(f"Unsupported layout type: {layout}")
    
    return f'<div class="dashboard-layout-{layout}">{content}</div>'

def escape_and_render(text: str) -> str:
    return html.escape(text)

def render_error_dashboard(title: str, error: str) -> str:
    return (f"<h1>{html.escape(title)}</h1>"
            "<div class='error-dashboard'>"
            f"<p>{html.escape(error)}</p></div>")

def render_empty_dashboard(title: str) -> str:
    return (f"<h1>{html.escape(title)}</h1>"
            "<div class='empty-dashboard'>"
            "Loading...</div>")

def render_dashboard_from_config(config: Dict[str, Union[str, dict]]) -> str:
    title = config.get("title")
    stats = config.get("stats", {})
    slots = config.get("slots", {})
    layout = config.get("layout", "grid")
    
    if not all([title, stats]):
        raise ConfigError("Missing required fields in configuration")
    
    cards = "".join(f'<div class="stat"><div class="label">{html.escape(str(k))}</div>'
                    f'<div class="value">{html.escape(str(v))}</div></div>' for k, v in stats.items())
    
    slot_content = "".join(slots.get(slot_key, "") for slot_key in config.get("slots", {}))
    
    return render_with_layout(f"<h1>{html.escape(title)}</h1><div class=\"stat-grid\">{cards}</div>{slot_content}", layout)

def render_dashboard(title: str, stats: Dict[str, Union[int, float]], slots: Optional[Dict[str, str]] = None) -> str:
    return render_dashboard_from_config({"title": title, "stats": stats, "slots": slots or {}})

def get_dashboard_data(session: Session):
    # Example query to fetch dashboard data from the database
    stmt = select(DashboardModel).limit(1)
    result = session.execute(stmt)
    return result.scalars().first()

class DashboardModel(BaseModel):
    title: str
    stats: Dict[str, Union[int, float]]
    slots: Optional[Dict[str, str]] = None

def render_dashboard_with_db_data(session: Session) -> str:
    dashboard_data = get_dashboard_data(session)
    if not dashboard_data:
        return render_empty_dashboard("No Data")
    
    return render_dashboard_from_config(dashboard_data.dict())


def _selftest() -> None:
    # cards + charts
    c = render_card("Revenue", "$1,234")
    assert '<div class="card">' in c and "<h2>Revenue</h2>" in c and "$1,234" in c
    ch = render_chart("c1", "bar", {"a": 1, "b": 2})
    assert 'id="c1"' in ch and "chart-bar" in ch
    # full dashboard render
    d = render_dashboard("Ops", {"Users": 42, "Errors": 3})
    assert "<h1>Ops</h1>" in d and "dashboard-layout-grid" in d
    assert "Users" in d and "42" in d
    # NEGATIVE: unsupported chart type / layout raise
    try:
        render_chart("c", "donut", {})
        raise AssertionError("bad chart type accepted")
    except ValueError:
        pass
    try:
        render_with_layout("x", "circular")
        raise AssertionError("bad layout accepted")
    except ValueError:
        pass
    # NEGATIVE: missing required config field raises ConfigError
    try:
        render_dashboard_from_config({"title": "x"})
        raise AssertionError("missing stats accepted")
    except ConfigError:
        pass
    # ADVERSARIAL: XSS in titles/values is escaped, never raw
    xss = "<script>alert(1)</script>"
    assert "<script>" not in render_card(xss, xss)
    assert "&lt;script&gt;" in render_card(xss, "safe")
    assert "<script>" not in render_dashboard(xss, {xss: xss})
    print("dashboards selftest OK")


if __name__ == "__main__":
    _selftest()
