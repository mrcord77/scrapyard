"""
select_field — a labeled, themed <select> primitive with error text.

### PART-META-JSON
{
  "name": "select_field",
  "layer": "ui",
  "purpose": "Render a labeled <select> from a list of (value, label) options with a selected value, required marker and an inline error message, styled entirely from design tokens so it matches any theme.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "name; label; options (list of (value, label) pairs); selected value; required bool; error text; placeholder text for an empty leading option.",
  "outputs": "render_select(...) -> a labeled <select> block as an HTML string; demo() -> str sample.",
  "files_created": [],
  "security_notes": "name, label, every option value and label, and the error text are escaped with html.escape, so an XSS payload such as <script> is rendered as &lt;script&gt; and cannot execute. Colors come only from var(--color-*) tokens.",
  "ai_usage": "from scrapyard.ui.select_field import render_select; html = render_select('plan', 'Plan', [('pro','Pro'),('free','Free')], selected='pro')",
  "example": "render_select('country', 'Country', [('us','United States')], required=True)",
  "import_path": "scrapyard.ui.select_field"
}
### END-PART-META
"""
from __future__ import annotations

import html
from typing import Iterable, Tuple

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
_ERROR_STYLE = (
    "display: block; font-size: var(--text-xs); color: var(--color-danger);"
    " margin-top: var(--space-1);"
)


def render_select(
    name: str,
    label: str,
    options: Iterable[Tuple[str, str]],
    *,
    selected: str | None = None,
    required: bool = False,
    error: str = "",
    placeholder: str = "",
) -> str:
    """Return a labeled <select>. `options` is a list of (value, label) pairs;
    `placeholder` adds a disabled empty leading option when set."""
    esc = html.escape
    nm = esc(name, quote=True)
    border = "var(--color-danger)" if error else "var(--color-border)"
    control_style = _CONTROL_STYLE + f" border: 1px solid {border};"

    req_mark = (
        ' <span style="color: var(--color-danger);" aria-hidden="true">*</span>'
        if required else ""
    )

    opt_html = []
    if placeholder:
        sel = " selected" if selected is None else ""
        opt_html.append(
            f'<option value="" disabled{sel}>{esc(placeholder)}</option>'
        )
    for value, text in options:
        v = esc(str(value), quote=True)
        sel = " selected" if selected is not None and str(value) == str(selected) else ""
        opt_html.append(f'<option value="{v}"{sel}>{esc(str(text))}</option>')

    attrs = [f'id="{nm}"', f'name="{nm}"']
    if required:
        attrs.append("required")
    if error:
        attrs.append('aria-invalid="true"')
    attrs.append(f'style="{control_style}"')

    out = [
        '<div style="margin-bottom: var(--space-4);">',
        f'<label for="{nm}" style="{_LABEL_STYLE}">{esc(label)}{req_mark}</label>',
        f"<select {' '.join(attrs)}>{''.join(opt_html)}</select>",
    ]
    if error:
        out.append(f'<small style="{_ERROR_STYLE}">{esc(error)}</small>')
    out.append("</div>")
    return "".join(out)


def demo() -> str:
    """Sample render: a selected plan and a required errored country picker."""
    return (
        render_select("plan", "Subscription plan",
                      [("free", "Free"), ("pro", "Pro"), ("team", "Team")],
                      selected="pro")
        + render_select("country", "Country",
                        [("us", "United States"), ("ca", "Canada")],
                        placeholder="Select a country", required=True,
                        error="Country is required.")
    )


def _selftest() -> None:
    sel = render_select("plan", "Plan",
                        [("free", "Free"), ("pro", "Pro")], selected="pro")
    assert '<label for="plan"' in sel and "<select " in sel
    assert '<option value="pro" selected>Pro</option>' in sel
    assert '<option value="free">Free</option>' in sel
    assert "var(--color-border)" in sel

    # placeholder + error state
    err = render_select("c", "C", [("x", "X")], placeholder="Pick", error="req")
    assert 'value="" disabled' in err and "Pick" in err
    assert "var(--color-danger)" in err and "req" in err

    # ADVERSARIAL: XSS in label, option value and option label are escaped
    xss = render_select("<n>", "<script>alert(1)</script>",
                        [('"><script>x()</script>', "<b>opt</b>")],
                        error="<i>e</i>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in xss
    assert "<script>" not in xss and "<b>opt</b>" not in xss

    print("select_field selftest OK")


if __name__ == "__main__":
    _selftest()
