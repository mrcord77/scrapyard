"""
input_field — a labeled, themed text input primitive with error/help text.

### PART-META-JSON
{
  "name": "input_field",
  "layer": "ui",
  "purpose": "Render a labeled <input> (any text-like type) with placeholder, value, required marker, an inline error message and optional help text, styled entirely from design tokens; a standalone styled primitive that complements the frontend/forms parts.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "name; label; type ('text'|'email'|'password'|...); value; placeholder; required bool; error text; help text.",
  "outputs": "render_input(...) -> a labeled input block as an HTML string; demo() -> str sample.",
  "files_created": [],
  "security_notes": "name, label, type, value, placeholder, error and help are all escaped with html.escape, so an XSS payload such as <script> becomes &lt;script&gt; and never executes. Styling is token-only via var(--color-*) with no raw color literals.",
  "ai_usage": "from scrapyard.ui.input_field import render_input; html = render_input('email', 'Email', type='email', required=True)",
  "example": "render_input('email', 'Email address', type='email', error='Invalid email')",
  "import_path": "scrapyard.ui.input_field"
}
### END-PART-META
"""
from __future__ import annotations

import html

STATUS = "core"

_LABEL_STYLE = (
    "display: block; font-family: var(--font-sans); font-size: var(--text-sm);"
    " font-weight: var(--weight-medium); color: var(--color-text);"
    " margin-bottom: var(--space-1);"
)
_CONTROL_STYLE = (
    "width: 100%; font-family: var(--font-sans); font-size: var(--text-base);"
    " color: var(--color-text); background: var(--color-surface);"
    " padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm);"
)
_HELP_STYLE = (
    "display: block; font-size: var(--text-xs); color: var(--color-text-muted);"
    " margin-top: var(--space-1);"
)
_ERROR_STYLE = (
    "display: block; font-size: var(--text-xs); color: var(--color-danger);"
    " margin-top: var(--space-1);"
)


def render_input(
    name: str,
    label: str,
    *,
    type: str = "text",
    value: str = "",
    placeholder: str = "",
    required: bool = False,
    error: str = "",
    help: str = "",
) -> str:
    """Return a labeled input block. When `error` is set the border turns danger
    and the message is shown; `help` shows a muted hint when there is no error."""
    esc = html.escape
    nm = esc(name, quote=True)
    border = "var(--color-danger)" if error else "var(--color-border)"
    control_style = _CONTROL_STYLE + f" border: 1px solid {border};"

    req_mark = (
        ' <span style="color: var(--color-danger);" aria-hidden="true">*</span>'
        if required else ""
    )
    attrs = [
        f'id="{nm}"',
        f'name="{nm}"',
        f'type="{esc(type, quote=True)}"',
        f'value="{esc(value, quote=True)}"',
    ]
    if placeholder:
        attrs.append(f'placeholder="{esc(placeholder, quote=True)}"')
    if required:
        attrs.append("required")
    if error:
        attrs.append('aria-invalid="true"')
    attrs.append(f'style="{control_style}"')

    out = [
        '<div style="margin-bottom: var(--space-4);">',
        f'<label for="{nm}" style="{_LABEL_STYLE}">{esc(label)}{req_mark}</label>',
        f"<input {' '.join(attrs)}>",
    ]
    if error:
        out.append(f'<small style="{_ERROR_STYLE}">{esc(error)}</small>')
    elif help:
        out.append(f'<small style="{_HELP_STYLE}">{esc(help)}</small>')
    out.append("</div>")
    return "".join(out)


def demo() -> str:
    """Sample render: a valid help-text field and an errored field."""
    return (
        render_input("email", "Email address", type="email",
                     placeholder="you@example.com", required=True,
                     help="We never share your email.")
        + render_input("code", "Access code", value="ABC-123",
                       error="That code has expired.")
    )


def _selftest() -> None:
    field = render_input("email", "Email", type="email", required=True,
                         help="No spam")
    assert '<label for="email"' in field and "Email" in field
    assert 'type="email"' in field and "required" in field
    assert "var(--color-border)" in field and "No spam" in field

    # error state swaps to the danger border + shows the message, hides help
    err = render_input("code", "Code", error="expired", help="hidden now")
    assert "var(--color-danger)" in err and "expired" in err
    assert "hidden now" not in err and 'aria-invalid="true"' in err

    # ADVERSARIAL: XSS in label, value and error are all escaped, never raw
    xss = render_input("<x>", "<script>alert(1)</script>",
                       value='"><script>bad()</script>',
                       error="<b>err</b>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in xss
    assert "<script>" not in xss and "<b>err</b>" not in xss

    print("input_field selftest OK")


if __name__ == "__main__":
    _selftest()
