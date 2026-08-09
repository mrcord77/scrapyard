"""
badge — small status pill with semantic variants and an optional count.

### PART-META-JSON
{
  "name": "badge",
  "layer": "ui",
  "purpose": "Render a compact status pill (a 'badge') in a semantic variant — primary, neutral, success, warning, danger, accent — with an optional numeric count. Used to label state, tags, or unread counts. Styled from design-token CSS variables so it inherits the active theme.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "label text; variant name; optional integer count.",
  "outputs": "render_badge(label, variant, count) -> HTML string; demo() -> gallery of variants.",
  "files_created": [],
  "security_notes": "The label is run through html.escape so markup in a caller string (e.g. <script>) becomes inert text. The count is coerced to int before rendering, so it cannot carry markup. Variant selection is a fixed internal map, not caller CSS.",
  "ai_usage": "from scrapyard.ui.badge import render_badge; html = render_badge('Active', variant='success'); html = render_badge('Inbox', count=12)",
  "example": "render_badge('Beta', variant='accent')",
  "import_path": "scrapyard.ui.badge"
}
### END-PART-META
"""
from __future__ import annotations

import html

STATUS = "core"

# variant -> (background token, text color). Solid pills use #fff/#000 text for
# contrast against the token fill; 'neutral' is a quiet surface chip.
_VARIANT = {
    "primary": ("--color-primary", "#fff"),
    "accent": ("--color-accent", "#fff"),
    "success": ("--color-success", "#000"),
    "warning": ("--color-warning", "#000"),
    "danger": ("--color-danger", "#fff"),
    "neutral": ("--color-surface", None),  # None -> use themed text color
}


def render_badge(label: str, *, variant: str = "primary", count: int | None = None) -> str:
    """Return a pill-shaped badge. `variant` picks the fill token; `count`, when
    given, is coerced to int and appended in a subtle counter."""
    bg, fg = _VARIANT.get(variant, _VARIANT["primary"])
    color = fg if fg is not None else "var(--color-text)"
    border = "" if variant != "neutral" else "border:1px solid var(--color-border);"
    style = (
        "display:inline-flex;align-items:center;gap:var(--space-1);"
        f"background:var({bg});color:{color};{border}"
        "font-family:var(--font-sans);font-size:var(--text-xs);"
        "font-weight:var(--weight-semibold);line-height:1;"
        "padding:var(--space-1) var(--space-2);border-radius:var(--radius-full);"
        "white-space:nowrap;vertical-align:middle;"
    )
    inner = html.escape(label)
    if count is not None:
        try:
            n = int(count)
        except (TypeError, ValueError):
            n = 0
        inner += (
            '<span style="opacity:.85;font-weight:var(--weight-bold);'
            f'padding-left:var(--space-1)">{n}</span>'
        )
    return f'<span class="sy-badge sy-badge-{html.escape(variant)}" style="{style}">{inner}</span>'


def demo() -> str:
    """A row of every variant plus a counted badge."""
    return (
        '<div style="display:flex;flex-wrap:wrap;gap:var(--space-2);align-items:center">'
        + render_badge("Primary", variant="primary")
        + render_badge("Beta", variant="accent")
        + render_badge("Active", variant="success")
        + render_badge("Pending", variant="warning")
        + render_badge("Failed", variant="danger")
        + render_badge("Draft", variant="neutral")
        + render_badge("Inbox", variant="primary", count=12)
        + "</div>"
    )


def _selftest() -> None:
    out = render_badge("Active", variant="success")
    assert "sy-badge" in out and "var(--color-success)" in out and "Active" in out

    # count is coerced to int and rendered
    counted = render_badge("Inbox", count=7)
    assert ">7<" in counted

    # a non-numeric count degrades to 0, never injects markup
    assert ">0<" in render_badge("x", count="<script>")  # type: ignore[arg-type]

    # unknown variant falls back to primary token
    assert "var(--color-primary)" in render_badge("y", variant="nope")

    # demo composes
    assert "sy-badge" in demo()

    # ADVERSARIAL (XSS): label markup is escaped, not raw
    evil = render_badge("<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in evil and "&lt;script&gt;" in evil

    print("badge selftest OK")


if __name__ == "__main__":
    _selftest()
