"""
footer — a site footer with link columns, copyright, and social links.

### PART-META-JSON
{
  "name": "footer",
  "layer": "ui",
  "purpose": "A site-wide footer part: several titled columns of navigation links, an optional row of social links, and a copyright line. Themed from the design tokens (surface/border/muted text/spacing) so it reads as the intentional bottom of a themed page.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Keyword args: columns (list of {title, links:[{label, href}]}), social (list of {label, href}), copyright (text).",
  "outputs": "render_footer(...) -> a <footer> HTML string using var(--color-surface)/var(--color-border)/var(--color-text-muted)/var(--space-*).",
  "files_created": [],
  "security_notes": "Every caller value (column titles, link labels, hrefs, social labels/hrefs, copyright) is escaped with html.escape and hrefs are quote-escaped, so untrusted link text or URLs cannot inject markup.",
  "ai_usage": "html = render_footer(columns=[{'title':'Product','links':[{'label':'Pricing','href':'/pricing'}]}], copyright='(c) 2026 Acme'); place at the end of a page body.",
  "example": "from scrapyard.ui.footer import render_footer; print(render_footer(copyright='(c) 2026 Acme'))",
  "import_path": "scrapyard.ui.footer"
}
### END-PART-META
"""
from __future__ import annotations

import html
from typing import Dict, List, Optional

STATUS = "core"

_FOOTER = (
    "background:var(--color-surface);border-top:1px solid var(--color-border);"
    "color:var(--color-text-muted);font-family:var(--font-sans);"
    "font-size:var(--text-sm);padding:var(--space-6) var(--space-5)"
)
_LINK = "color:var(--color-text-muted);text-decoration:none"


def _link(label: str, href: str) -> str:
    return (f'<a href="{html.escape(str(href), quote=True)}" '
            f'style="{_LINK}">{html.escape(str(label))}</a>')


def render_footer(*, columns: Optional[List[Dict[str, object]]] = None,
                  social: Optional[List[Dict[str, str]]] = None,
                  copyright: str = "") -> str:
    """Render a themed footer. All caller text and hrefs are escaped."""
    parts: List[str] = [f'<footer class="sy-footer" style="{_FOOTER}">']

    if columns:
        parts.append(
            '<div style="display:flex;flex-wrap:wrap;gap:var(--space-8);'
            'margin-bottom:var(--space-5)">'
        )
        for col in columns:
            title = html.escape(str(col.get("title", "")))
            links: List[Dict[str, str]] = list(col.get("links", []))  # type: ignore[arg-type]
            items = "".join(
                f'<li style="margin-bottom:var(--space-2)">'
                f'{_link(l.get("label", ""), l.get("href", "#"))}</li>'
                for l in links
            )
            parts.append(
                '<nav style="min-width:var(--space-10)">'
                '<h4 style="margin:0 0 var(--space-3);color:var(--color-text);'
                f'font-size:var(--text-sm);font-weight:var(--weight-semibold)">{title}</h4>'
                f'<ul style="list-style:none;margin:0;padding:0">{items}</ul></nav>'
            )
        parts.append('</div>')

    bar = []
    if copyright:
        bar.append(f'<span>{html.escape(copyright)}</span>')
    if social:
        links = "".join(
            f'<span style="margin-left:var(--space-3)">'
            f'{_link(s.get("label", ""), s.get("href", "#"))}</span>'
            for s in social
        )
        bar.append(f'<div>{links}</div>')
    if bar:
        parts.append(
            '<div style="display:flex;flex-wrap:wrap;gap:var(--space-3);'
            'align-items:center;justify-content:space-between;'
            'border-top:1px solid var(--color-border);padding-top:var(--space-4)">'
            + "".join(bar) + '</div>'
        )

    parts.append('</footer>')
    return "".join(parts)


def demo() -> str:
    """Self-contained sample footer with columns, social links, and copyright."""
    return render_footer(
        columns=[
            {"title": "Product", "links": [
                {"label": "Features", "href": "/features"},
                {"label": "Pricing", "href": "/pricing"}]},
            {"title": "Company", "links": [
                {"label": "About", "href": "/about"},
                {"label": "Careers", "href": "/careers"}]},
        ],
        social=[{"label": "GitHub", "href": "https://example.com/gh"},
                {"label": "X", "href": "https://example.com/x"}],
        copyright="(c) 2026 Scrapyard Labs",
    )


def _selftest() -> None:
    out = render_footer(
        columns=[{"title": "Product", "links": [{"label": "Pricing", "href": "/p"}]}],
        social=[{"label": "GitHub", "href": "/gh"}],
        copyright="(c) 2026 Acme")
    assert out.startswith('<footer class="sy-footer"') and out.endswith("</footer>")
    assert "var(--color-surface)" in out and "var(--color-border)" in out
    assert "Product" in out and 'href="/p"' in out and ">Pricing<" in out
    assert ">GitHub<" in out and "(c) 2026 Acme" in out
    # href escaping
    esc = render_footer(social=[{"label": "q", "href": "/s?a=1&b=2"}])
    assert "&amp;" in esc
    # ADVERSARIAL: injected markup in a link label is escaped
    xss = render_footer(columns=[{"title": "<b>x</b>", "links": [
        {"label": "<script>alert(1)</script>", "href": "/z"}]}])
    assert "<script>alert(1)</script>" not in xss and "&lt;script&gt;" in xss
    assert "<b>x</b>" not in xss
    print("footer selftest OK")


if __name__ == "__main__":
    _selftest()
