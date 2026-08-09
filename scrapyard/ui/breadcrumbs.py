"""
breadcrumbs — an accessible navigation trail with a current-page marker.

### PART-META-JSON
{
  "name": "breadcrumbs",
  "layer": "ui",
  "purpose": "Render an ordered breadcrumb trail from a list of {label, href}. Every crumb but the last is a link; the last crumb is the current location and is marked aria-current='page'. Separators sit between crumbs. Themed from the design tokens (muted text, primary links, spacing).",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "trail: list of {label, href}; optional separator string.",
  "outputs": "render_breadcrumbs(trail, separator='/') -> a <nav><ol>...</ol></nav> HTML string using var(--color-text-muted)/var(--color-primary)/var(--space-*).",
  "files_created": [],
  "security_notes": "Crumb labels, hrefs, and the separator are all escaped with html.escape (hrefs quote-escaped), so untrusted path segments cannot inject markup. The last crumb renders as text (no href), matching current-page semantics.",
  "ai_usage": "html = render_breadcrumbs([{'label':'Home','href':'/'},{'label':'Docs','href':'/docs'},{'label':'API'}]); place above page content.",
  "example": "from scrapyard.ui.breadcrumbs import render_breadcrumbs; print(render_breadcrumbs([{'label':'Home','href':'/'},{'label':'Now'}]))",
  "import_path": "scrapyard.ui.breadcrumbs"
}
### END-PART-META
"""
from __future__ import annotations

import html
from typing import Dict, List

STATUS = "core"

_NAV = ("font-family:var(--font-sans);font-size:var(--text-sm);"
        "color:var(--color-text-muted)")
_OL = ("list-style:none;display:flex;flex-wrap:wrap;align-items:center;"
       "gap:var(--space-2);margin:0;padding:0")
_LINK = "color:var(--color-primary);text-decoration:none"
_CURRENT = "color:var(--color-text);font-weight:var(--weight-medium)"
_SEP = "color:var(--color-text-muted);user-select:none"


def render_breadcrumbs(trail: List[Dict[str, str]], *, separator: str = "/") -> str:
    """Render a breadcrumb trail; the final crumb is the current page."""
    crumbs = list(trail or [])
    sep = html.escape(str(separator))
    items: List[str] = []
    last = len(crumbs) - 1
    for i, crumb in enumerate(crumbs):
        label = html.escape(str(crumb.get("label", "")))
        href = crumb.get("href")
        if i == last or not href:
            cell = f'<span aria-current="page" style="{_CURRENT}">{label}</span>'
        else:
            cell = (f'<a href="{html.escape(str(href), quote=True)}" '
                    f'style="{_LINK}">{label}</a>')
        if i > 0:
            items.append(f'<li aria-hidden="true" style="{_SEP}">{sep}</li>')
        items.append(f'<li style="display:flex;align-items:center">{cell}</li>')
    return (f'<nav aria-label="Breadcrumb" class="sy-breadcrumbs" style="{_NAV}">'
            f'<ol style="{_OL}">{"".join(items)}</ol></nav>')


def demo() -> str:
    """Self-contained sample: a three-level breadcrumb trail."""
    return render_breadcrumbs([
        {"label": "Home", "href": "/"},
        {"label": "Reports", "href": "/reports"},
        {"label": "Q3 Summary"},
    ])


def _selftest() -> None:
    out = render_breadcrumbs([
        {"label": "Home", "href": "/"},
        {"label": "Docs", "href": "/docs"},
        {"label": "API"}])
    assert out.startswith('<nav aria-label="Breadcrumb"') and out.endswith("</nav>")
    assert "var(--color-primary)" in out and "var(--color-text-muted)" in out
    # non-final crumbs are links, final crumb is aria-current text (no href)
    assert 'href="/docs"' in out and ">Docs<" in out
    assert 'aria-current="page"' in out and ">API<" in out
    assert out.count("<li") == 5  # 3 crumbs + 2 separators
    # separator between crumbs
    assert render_breadcrumbs(
        [{"label": "a", "href": "/"}, {"label": "b"}], separator=">").count(">&gt;<") == 1
    # ADVERSARIAL: label markup is escaped
    xss = render_breadcrumbs([{"label": "<script>alert(1)</script>", "href": "/"},
                              {"label": "here"}])
    assert "<script>alert(1)</script>" not in xss and "&lt;script&gt;" in xss
    print("breadcrumbs selftest OK")


if __name__ == "__main__":
    _selftest()
