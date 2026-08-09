"""
button — a themed, XSS-safe HTML button primitive.

### PART-META-JSON
{
  "name": "button",
  "layer": "ui",
  "purpose": "Render a themed <button> with primary/secondary/danger variants, sm/md/lg sizes, a disabled state, an optional (escaped) icon slot and a settable type, styled only through design tokens so it matches any theme.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "label text; variant ('primary'|'secondary'|'danger'); size ('sm'|'md'|'lg'); type ('button'|'submit'|'reset'); disabled bool; optional icon text; optional name/value.",
  "outputs": "render_button(...) -> a single <button> HTML string; demo() -> str sample; VARIANTS/SIZES tables.",
  "files_created": [],
  "security_notes": "Every caller value (label, icon, type, name, value) is escaped with html.escape before it reaches the markup, so an XSS payload such as <script> is neutralized to &lt;script&gt;. Colors come only from var(--color-*) tokens; nothing is emitted raw.",
  "ai_usage": "from scrapyard.ui.button import render_button; html = render_button('Save', variant='primary', type='submit')",
  "example": "render_button('Delete', variant='danger', size='sm', icon='x')",
  "import_path": "scrapyard.ui.button"
}
### END-PART-META
"""
from __future__ import annotations

import html

STATUS = "core"

# variant -> (background token, text color, extra style)
VARIANTS = {
    "primary": "background: var(--color-primary); color: #fff; border: 1px solid var(--color-primary);",
    "secondary": "background: var(--color-surface); color: var(--color-text); border: 1px solid var(--color-border);",
    "danger": "background: var(--color-danger); color: #fff; border: 1px solid var(--color-danger);",
}

# size -> (font-size token, padding)
SIZES = {
    "sm": "font-size: var(--text-sm); padding: var(--space-1) var(--space-3);",
    "md": "font-size: var(--text-base); padding: var(--space-2) var(--space-4);",
    "lg": "font-size: var(--text-lg); padding: var(--space-3) var(--space-5);",
}

_TYPES = {"button", "submit", "reset"}

_BASE_STYLE = (
    "display: inline-flex; align-items: center; gap: var(--space-2);"
    " font-family: var(--font-sans); font-weight: var(--weight-medium);"
    " line-height: var(--leading-tight); border-radius: var(--radius-sm);"
    " box-shadow: var(--shadow-sm); cursor: pointer;"
)


def render_button(
    label: str,
    *,
    variant: str = "primary",
    size: str = "md",
    type: str = "button",
    disabled: bool = False,
    icon: str | None = None,
    name: str | None = None,
    value: str | None = None,
) -> str:
    """Return one themed <button>. Unknown variant/size fall back to primary/md.
    `icon` is treated as text and escaped (safe for emoji/glyphs)."""
    variant_style = VARIANTS.get(variant, VARIANTS["primary"])
    size_style = SIZES.get(size, SIZES["md"])
    btype = type if type in _TYPES else "button"

    style = _BASE_STYLE + " " + variant_style + " " + size_style
    if disabled:
        style += " opacity: 0.55; cursor: not-allowed;"

    attrs = [f'type="{html.escape(btype, quote=True)}"']
    if name is not None:
        attrs.append(f'name="{html.escape(name, quote=True)}"')
    if value is not None:
        attrs.append(f'value="{html.escape(value, quote=True)}"')
    if disabled:
        attrs.append("disabled")
    attrs.append(f'style="{style}"')

    inner = ""
    if icon is not None:
        inner += f'<span aria-hidden="true">{html.escape(icon)}</span>'
    inner += f"<span>{html.escape(label)}</span>"

    return f"<button {' '.join(attrs)}>{inner}</button>"


def demo() -> str:
    """Sample render: the three variants across sizes plus a disabled state."""
    parts = [
        render_button("Save changes", variant="primary", type="submit"),
        render_button("Cancel", variant="secondary"),
        render_button("Delete account", variant="danger", size="sm", icon="x"),
        render_button("Processing", variant="primary", size="lg", disabled=True),
    ]
    return (
        '<div style="display: flex; gap: var(--space-3); flex-wrap: wrap;'
        ' align-items: center;">' + "".join(parts) + "</div>"
    )


def _selftest() -> None:
    primary = render_button("Go", variant="primary")
    assert primary.startswith("<button ") and primary.endswith("</button>")
    assert "var(--color-primary)" in primary
    assert 'type="button"' in primary

    # secondary uses surface/border tokens, not the primary color background
    secondary = render_button("Back", variant="secondary")
    assert "var(--color-surface)" in secondary and "var(--color-border)" in secondary

    # sizes and disabled state are reflected structurally
    assert "var(--text-lg)" in render_button("Big", size="lg")
    dis = render_button("Nope", disabled=True)
    assert " disabled" in dis and "not-allowed" in dis

    # submit type honored, junk type falls back
    assert 'type="submit"' in render_button("S", type="submit")
    assert 'type="button"' in render_button("S", type="javascript:alert(1)")

    # ADVERSARIAL: an XSS payload in the label is escaped, never raw
    xss = render_button("<script>alert(1)</script>", icon="<img src=x>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in xss
    assert "<script>" not in xss and "<img src=x>" not in xss

    print("button selftest OK")


if __name__ == "__main__":
    _selftest()
