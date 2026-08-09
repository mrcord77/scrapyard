"""
textarea — a labeled, themed multiline <textarea> primitive with error text.

### PART-META-JSON
{
  "name": "textarea",
  "layer": "ui",
  "purpose": "Render a labeled multiline <textarea> with a row count, initial value, placeholder, required marker, help text and an inline error message, styled entirely from design tokens so it matches any theme.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "name; label; value; rows int; placeholder; required bool; error text; help text.",
  "outputs": "render_textarea(...) -> a labeled <textarea> block as an HTML string; demo() -> str sample.",
  "files_created": [],
  "security_notes": "name, label, value, placeholder, error and help are escaped with html.escape, so an XSS payload such as <script> in the body content becomes &lt;script&gt; and cannot execute. Styling is token-only via var(--color-*).",
  "ai_usage": "from scrapyard.ui.textarea import render_textarea; html = render_textarea('bio', 'Bio', rows=5)",
  "example": "render_textarea('notes', 'Notes', value='hello', rows=6, error='Too long')",
  "import_path": "scrapyard.ui.textarea"
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
    " line-height: var(--leading-normal); color: var(--color-text);"
    " background: var(--color-surface); padding: var(--space-2) var(--space-3);"
    " border-radius: var(--radius-sm); resize: vertical;"
)
_HELP_STYLE = (
    "display: block; font-size: var(--text-xs); color: var(--color-text-muted);"
    " margin-top: var(--space-1);"
)
_ERROR_STYLE = (
    "display: block; font-size: var(--text-xs); color: var(--color-danger);"
    " margin-top: var(--space-1);"
)


def render_textarea(
    name: str,
    label: str,
    *,
    value: str = "",
    rows: int = 4,
    placeholder: str = "",
    required: bool = False,
    error: str = "",
    help: str = "",
) -> str:
    """Return a labeled <textarea> block. `rows` is coerced to a positive int;
    an `error` swaps the border to danger and shows the message."""
    esc = html.escape
    nm = esc(name, quote=True)
    try:
        nrows = max(1, int(rows))
    except (TypeError, ValueError):
        nrows = 4
    border = "var(--color-danger)" if error else "var(--color-border)"
    control_style = _CONTROL_STYLE + f" border: 1px solid {border};"

    req_mark = (
        ' <span style="color: var(--color-danger);" aria-hidden="true">*</span>'
        if required else ""
    )
    attrs = [f'id="{nm}"', f'name="{nm}"', f'rows="{nrows}"']
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
        f"<textarea {' '.join(attrs)}>{esc(value)}</textarea>",
    ]
    if error:
        out.append(f'<small style="{_ERROR_STYLE}">{esc(error)}</small>')
    elif help:
        out.append(f'<small style="{_HELP_STYLE}">{esc(help)}</small>')
    out.append("</div>")
    return "".join(out)


def demo() -> str:
    """Sample render: a help-text bio and an errored message field."""
    return (
        render_textarea("bio", "Short bio", rows=5,
                        placeholder="Tell us about yourself",
                        help="Markdown supported.")
        + render_textarea("msg", "Message", value="Draft text",
                          rows=3, error="Message is too long.")
    )


def _selftest() -> None:
    ta = render_textarea("bio", "Bio", value="hi", rows=6, help="ok")
    assert '<label for="bio"' in ta and "<textarea " in ta
    assert 'rows="6"' in ta and ">hi</textarea>" in ta
    assert "var(--color-border)" in ta and "ok" in ta

    # bad rows coerce to default; error swaps border + hides help
    assert 'rows="4"' in render_textarea("x", "X", rows="oops")
    err = render_textarea("m", "M", error="too long", help="hidden")
    assert "var(--color-danger)" in err and "too long" in err
    assert "hidden" not in err and 'aria-invalid="true"' in err

    # ADVERSARIAL: XSS in the body value and label are escaped, never raw
    xss = render_textarea("<n>", "<script>alert(1)</script>",
                          value="</textarea><script>bad()</script>",
                          error="<b>e</b>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in xss
    assert "<script>" not in xss and "<b>e</b>" not in xss

    print("textarea selftest OK")


if __name__ == "__main__":
    _selftest()
