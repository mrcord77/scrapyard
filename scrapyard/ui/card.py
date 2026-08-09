"""
card — a themed content container with header/body/footer slots.

### PART-META-JSON
{
  "name": "card",
  "layer": "ui",
  "purpose": "A reusable content-container part: an optional cover image, a header (title + subtitle), a free-form body slot, an optional action-button row, and an optional footer. Styled entirely from the design tokens (surface/border/radius/shadow/spacing) so cards look native to whatever theme the page applies.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Keyword args: title, subtitle, body (pre-rendered HTML slot), image_src, image_alt, actions (list of {label, href}), footer.",
  "outputs": "render_card(...) -> a <article> HTML string using var(--color-surface)/var(--radius-lg)/var(--shadow-md)/var(--space-*).",
  "files_created": [],
  "security_notes": "All caller TEXT (title, subtitle, image_alt, image_src, action labels/hrefs, footer) is escaped with html.escape (hrefs/src quoted). The body argument is a composition slot inserted verbatim and MUST already be valid/escaped HTML by the caller, mirroring css_baseline.render_document.",
  "ai_usage": "html = render_card(title='Report', subtitle='Q3', body='<p>...</p>', actions=[{'label':'Open','href':'/r/3'}]); embed in a page body.",
  "example": "from scrapyard.ui.card import render_card; print(render_card(title='Hi', body='<p>Body</p>'))",
  "import_path": "scrapyard.ui.card"
}
### END-PART-META
"""
from __future__ import annotations

import html
from typing import Dict, List, Optional

STATUS = "core"

_CARD = (
    "background:var(--color-surface);border:1px solid var(--color-border);"
    "border-radius:var(--radius-lg);box-shadow:var(--shadow-md);overflow:hidden;"
    "font-family:var(--font-sans);color:var(--color-text)"
)
_BTN = (
    "display:inline-block;padding:var(--space-2) var(--space-4);"
    "border-radius:var(--radius-sm);background:var(--color-primary);color:#fff;"
    "font-size:var(--text-sm);font-weight:var(--weight-medium);text-decoration:none"
)


def render_card(*, title: Optional[str] = None, subtitle: Optional[str] = None,
                body: str = "", image_src: Optional[str] = None,
                image_alt: str = "", actions: Optional[List[Dict[str, str]]] = None,
                footer: Optional[str] = None) -> str:
    """Render a themed card. Text fields are escaped; `body` is a verbatim slot."""
    parts: List[str] = [f'<article class="sy-card" style="{_CARD}">']

    if image_src:
        parts.append(
            f'<img src="{html.escape(str(image_src), quote=True)}" '
            f'alt="{html.escape(image_alt)}" '
            'style="display:block;width:100%;height:auto;object-fit:cover">'
        )

    if title or subtitle:
        parts.append('<header style="padding:var(--space-4) var(--space-5) 0">')
        if title:
            parts.append(
                '<h3 style="margin:0;font-size:var(--text-xl);'
                f'font-weight:var(--weight-semibold)">{html.escape(title)}</h3>'
            )
        if subtitle:
            parts.append(
                '<p style="margin:var(--space-1) 0 0;color:var(--color-text-muted);'
                f'font-size:var(--text-sm)">{html.escape(subtitle)}</p>'
            )
        parts.append('</header>')

    if body:
        parts.append(f'<div style="padding:var(--space-4) var(--space-5)">{body}</div>')

    if actions:
        btns = []
        for a in actions:
            label = html.escape(str(a.get("label", "")))
            href = html.escape(str(a.get("href", "#")), quote=True)
            btns.append(f'<a href="{href}" style="{_BTN}">{label}</a>')
        parts.append(
            '<div style="display:flex;gap:var(--space-2);'
            'padding:0 var(--space-5) var(--space-4)">' + "".join(btns) + '</div>'
        )

    if footer:
        parts.append(
            '<footer style="padding:var(--space-3) var(--space-5);'
            'border-top:1px solid var(--color-border);color:var(--color-text-muted);'
            f'font-size:var(--text-sm)">{html.escape(footer)}</footer>'
        )

    parts.append('</article>')
    return "".join(parts)


def demo() -> str:
    """Self-contained sample: a card with every slot populated."""
    return render_card(
        title="Deployment #482",
        subtitle="production - us-east",
        body="<p>All 14 checks passed. Rolled out to 3 regions in 92s.</p>",
        actions=[{"label": "View logs", "href": "/deploy/482"},
                 {"label": "Rollback", "href": "/deploy/482/rollback"}],
        footer="Updated 2 minutes ago",
    )


def _selftest() -> None:
    out = render_card(title="Title", subtitle="Sub", body="<p>Body</p>",
                      actions=[{"label": "Go", "href": "/x"}], footer="Foot")
    # structure + token styling present
    assert out.startswith('<article class="sy-card"') and out.endswith("</article>")
    assert "var(--color-surface)" in out and "var(--radius-lg)" in out
    assert "var(--shadow-md)" in out
    # slots rendered
    assert "Title" in out and "Sub" in out and "<p>Body</p>" in out
    assert 'href="/x"' in out and ">Go<" in out and "Foot" in out
    # image slot escapes its attributes
    img = render_card(image_src="/a.png?x=1&y=2", image_alt="a & b", title="I")
    assert "&amp;" in img
    # ADVERSARIAL: a script in a text field is escaped, not emitted live
    xss = render_card(title="<script>alert(1)</script>",
                      footer="<img src=x onerror=alert(1)>")
    assert "<script>alert(1)</script>" not in xss
    assert "&lt;script&gt;" in xss and "onerror=alert(1)>" not in xss
    print("card selftest OK")


if __name__ == "__main__":
    _selftest()
