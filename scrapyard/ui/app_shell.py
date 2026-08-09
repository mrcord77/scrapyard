"""
app_shell — page scaffold: top bar + left nav sidebar + main region.

### PART-META-JSON
{
  "name": "app_shell",
  "layer": "ui",
  "purpose": "The outer page layout for an app: a sticky top bar (brand + actions slot), a left sidebar of nav items (each with an optional icon and an active state), and a main content region. Collapses the sidebar to a horizontal strip on narrow viewports via a scoped media query. Themed from the design tokens (surface/border/primary/spacing/z).",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Keyword args: brand (text), nav_items (list of {label, href, icon?, active?}), content (pre-rendered HTML slot), actions (pre-rendered HTML slot), active (href to mark active).",
  "outputs": "render_app_shell(...) -> a <div> layout (with a scoped <style>) using var(--color-surface)/var(--color-border)/var(--color-primary)/var(--space-*)/var(--z-sticky).",
  "files_created": [],
  "security_notes": "brand, nav labels, hrefs, and icons are escaped with html.escape (hrefs quote-escaped). content and actions are composition slots inserted verbatim and MUST already be valid/escaped HTML by the caller.",
  "ai_usage": "html = render_app_shell(brand='Acme', nav_items=[{'label':'Home','href':'/','icon':'H','active':True}], content=page_html, actions=avatar_html).",
  "example": "from scrapyard.ui.app_shell import render_app_shell; print(render_app_shell(brand='Acme', nav_items=[{'label':'Home','href':'/'}]))",
  "import_path": "scrapyard.ui.app_shell"
}
### END-PART-META
"""
from __future__ import annotations

import html
from typing import Dict, List, Optional

STATUS = "core"

_STYLE = """\
<style>
.sy-shell{display:grid;grid-template-columns:var(--space-12) 1fr;grid-template-rows:auto 1fr;min-height:100vh;font-family:var(--font-sans);color:var(--color-text);background:var(--color-base)}
.sy-shell__bar{grid-column:1 / 3;display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);padding:var(--space-3) var(--space-5);background:var(--color-surface);border-bottom:1px solid var(--color-border);position:sticky;top:0;z-index:var(--z-sticky)}
.sy-shell__brand{font-size:var(--text-lg);font-weight:var(--weight-bold);color:var(--color-text);text-decoration:none}
.sy-shell__actions{display:flex;align-items:center;gap:var(--space-2)}
.sy-shell__side{grid-column:1;background:var(--color-surface);border-right:1px solid var(--color-border);padding:var(--space-3)}
.sy-shell__nav{display:flex;flex-direction:column;gap:var(--space-1);list-style:none;margin:0;padding:0}
.sy-shell__link{display:flex;align-items:center;gap:var(--space-2);padding:var(--space-2) var(--space-3);border-radius:var(--radius-md);color:var(--color-text-muted);text-decoration:none;font-size:var(--text-sm)}
.sy-shell__link:hover{background:var(--color-base);color:var(--color-text)}
.sy-shell__link[aria-current="page"]{background:var(--color-primary);color:#fff;font-weight:var(--weight-medium)}
.sy-shell__icon{width:var(--space-4);text-align:center}
.sy-shell__main{grid-column:2;padding:var(--space-5)}
@media (max-width:640px){
 .sy-shell{grid-template-columns:1fr}
 .sy-shell__bar{grid-column:1}
 .sy-shell__side{grid-column:1;border-right:0;border-bottom:1px solid var(--color-border)}
 .sy-shell__nav{flex-direction:row;flex-wrap:wrap}
 .sy-shell__main{grid-column:1}
}
</style>"""


def _nav_item(item: Dict[str, object], active_href: Optional[str]) -> str:
    label = html.escape(str(item.get("label", "")))
    href = html.escape(str(item.get("href", "#")), quote=True)
    icon = item.get("icon")
    is_active = bool(item.get("active")) or (
        active_href is not None and str(item.get("href", "")) == active_href)
    icon_html = (f'<span class="sy-shell__icon" aria-hidden="true">'
                 f'{html.escape(str(icon))}</span>') if icon else ""
    cur = ' aria-current="page"' if is_active else ""
    return (f'<li><a class="sy-shell__link"{cur} href="{href}">'
            f'{icon_html}<span>{label}</span></a></li>')


def render_app_shell(*, brand: str = "", nav_items: Optional[List[Dict[str, object]]] = None,
                     content: str = "", actions: str = "",
                     active: Optional[str] = None) -> str:
    """Render the app shell. brand/nav are escaped; content/actions are slots."""
    items = "".join(_nav_item(it, active) for it in (nav_items or []))
    return (
        f'{_STYLE}<div class="sy-shell">'
        f'<header class="sy-shell__bar">'
        f'<a class="sy-shell__brand" href="/">{html.escape(brand)}</a>'
        f'<div class="sy-shell__actions">{actions}</div>'
        f'</header>'
        f'<aside class="sy-shell__side"><nav aria-label="Primary">'
        f'<ul class="sy-shell__nav">{items}</ul></nav></aside>'
        f'<main class="sy-shell__main">{content}</main>'
        f'</div>'
    )


def demo() -> str:
    """Self-contained sample: a shell with a brand, four nav items, and content."""
    return render_app_shell(
        brand="Scrapyard",
        nav_items=[
            {"label": "Dashboard", "href": "/", "icon": "H", "active": True},
            {"label": "Parts", "href": "/parts", "icon": "P"},
            {"label": "Builds", "href": "/builds", "icon": "B"},
            {"label": "Settings", "href": "/settings", "icon": "S"},
        ],
        actions='<button>New</button>',
        content="<h1>Dashboard</h1><p>Welcome back.</p>",
    )


def _selftest() -> None:
    out = render_app_shell(
        brand="Acme",
        nav_items=[{"label": "Home", "href": "/", "icon": "H", "active": True},
                   {"label": "Docs", "href": "/docs"}],
        content="<h1>Body</h1>", actions="<span>hi</span>")
    assert 'class="sy-shell"' in out and "@media (max-width:640px)" in out
    assert "var(--color-surface)" in out and "var(--z-sticky)" in out
    assert "var(--color-primary)" in out  # active link style
    # active state applied to the matching item only
    assert 'aria-current="page" href="/"' in out
    assert 'aria-current="page" href="/docs"' not in out
    # slots inserted verbatim
    assert "<h1>Body</h1>" in out and "<span>hi</span>" in out
    # active-by-href param also works
    byhref = render_app_shell(nav_items=[{"label": "X", "href": "/x"}], active="/x")
    assert 'aria-current="page" href="/x"' in byhref
    # ADVERSARIAL: nav label + brand markup is escaped
    xss = render_app_shell(brand="<script>alert(1)</script>",
                           nav_items=[{"label": "<b>n</b>", "href": "/"}])
    assert "<script>alert(1)</script>" not in xss and "&lt;script&gt;" in xss
    assert "<b>n</b>" not in xss
    print("app_shell selftest OK")


if __name__ == "__main__":
    _selftest()
