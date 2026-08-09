"""
alert — inline status banner (info/success/warning/danger) built on theme tokens.

### PART-META-JSON
{
  "name": "alert",
  "layer": "ui",
  "purpose": "Render an inline alert/banner in one of four semantic variants (info, success, warning, danger) with an optional title, a message, and an optional dismiss button. Styled entirely from design-token CSS variables so it matches whatever theme the page applies.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "message text; variant ('info'|'success'|'warning'|'danger'); optional title; dismissible flag.",
  "outputs": "render_alert(message, variant, title, dismissible) -> HTML string; demo() -> sample render of every variant.",
  "files_created": [],
  "security_notes": "All caller-supplied text (title, message) is passed through html.escape before it reaches the markup, so a payload like <script> is rendered as inert text, never executed. Only a fixed internal variant->token map controls styling; the caller cannot inject CSS.",
  "ai_usage": "from scrapyard.ui.alert import render_alert; html = render_alert('Saved.', variant='success', title='Done', dismissible=True)",
  "example": "render_alert('Disk almost full', variant='warning', title='Heads up')",
  "import_path": "scrapyard.ui.alert"
}
### END-PART-META
"""
from __future__ import annotations

import html

STATUS = "core"

# variant -> the accent color token used for the left rule + title
_VARIANT = {
    "info": "--color-accent",
    "success": "--color-success",
    "warning": "--color-warning",
    "danger": "--color-danger",
}


def render_alert(
    message: str,
    *,
    variant: str = "info",
    title: str | None = None,
    dismissible: bool = False,
) -> str:
    """Return an alert banner as an HTML string.

    `variant` selects the semantic token color; unknown variants fall back to
    'info'. `title` and `message` are escaped. When `dismissible`, a close
    button removes the banner via a tiny inline handler (no library needed)."""
    accent = _VARIANT.get(variant, _VARIANT["info"])
    style = (
        "display:flex;gap:var(--space-3);align-items:flex-start;"
        "background:var(--color-surface);color:var(--color-text);"
        "border:1px solid var(--color-border);"
        f"border-left:4px solid var({accent});"
        "border-radius:var(--radius-md);padding:var(--space-3) var(--space-4);"
        "font-size:var(--text-sm);line-height:var(--leading-normal);"
    )
    parts = [f'<div class="sy-alert sy-alert-{html.escape(variant)}" role="alert" style="{style}">']
    parts.append('<div style="flex:1;min-width:0">')
    if title:
        parts.append(
            f'<strong style="display:block;color:var({accent});'
            f'font-weight:var(--weight-semibold);font-size:var(--text-base);'
            f'margin-bottom:var(--space-1)">{html.escape(title)}</strong>'
        )
    parts.append(f"<span>{html.escape(message)}</span>")
    parts.append("</div>")
    if dismissible:
        btn = (
            "background:transparent;color:var(--color-text-muted);border:0;"
            "cursor:pointer;font-size:var(--text-lg);line-height:1;"
            "padding:0 var(--space-1);"
        )
        parts.append(
            f'<button type="button" aria-label="Dismiss" style="{btn}" '
            f"onclick=\"this.closest('.sy-alert').remove()\">&times;</button>"
        )
    parts.append("</div>")
    return "".join(parts)


def demo() -> str:
    """One banner per variant, the last dismissible."""
    return (
        '<div style="display:flex;flex-direction:column;gap:var(--space-3)">'
        + render_alert("Deployment queued for release channel.", variant="info", title="Info")
        + render_alert("Backup completed with no errors.", variant="success", title="Success")
        + render_alert("Certificate expires in 3 days.", variant="warning", title="Warning")
        + render_alert("Payment failed — card was declined.", variant="danger",
                       title="Error", dismissible=True)
        + "</div>"
    )


def _selftest() -> None:
    out = render_alert("hello", variant="success", title="Done")
    assert 'role="alert"' in out
    assert "var(--color-success)" in out           # success variant token used
    assert "hello" in out and "Done" in out

    # dismiss button only when requested
    assert "Dismiss" not in render_alert("x")
    assert "Dismiss" in render_alert("x", dismissible=True)

    # unknown variant falls back to info's accent token, never crashes
    assert "var(--color-accent)" in render_alert("y", variant="bogus")

    # demo composes and is non-empty
    d = demo()
    assert isinstance(d, str) and d.strip() and "sy-alert" in d

    # ADVERSARIAL (XSS): a <script> payload in text is escaped, not raw
    evil = render_alert("<script>alert(1)</script>", title="<b>x</b>")
    assert "<script>alert(1)</script>" not in evil
    assert "&lt;script&gt;" in evil and "&lt;b&gt;" in evil

    print("alert selftest OK")


if __name__ == "__main__":
    _selftest()
