"""
checkbox_radio — themed, XSS-safe checkbox and radio-group primitives.

### PART-META-JSON
{
  "name": "checkbox_radio",
  "layer": "ui",
  "purpose": "Render a single labeled checkbox and a labeled radio-group (a shared name across value/label options with one checked) styled entirely from design tokens, so boolean and single-choice inputs match any theme.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "checkbox: name, label, value, checked, disabled. radio group: name, legend, options (list of (value, label)), selected value, disabled.",
  "outputs": "render_checkbox(...) -> a labeled checkbox HTML string; render_radio_group(...) -> a fieldset of radios; demo() -> str sample.",
  "files_created": [],
  "security_notes": "name, label, legend, and every option value/label are escaped with html.escape, so an XSS payload such as <script> becomes &lt;script&gt; and cannot execute. Accent and text colors come only from var(--color-*) tokens.",
  "ai_usage": "from scrapyard.ui.checkbox_radio import render_checkbox, render_radio_group; html = render_radio_group('size','Size',[('s','Small'),('l','Large')], selected='s')",
  "example": "render_checkbox('tos', 'I agree to the terms', checked=True)",
  "import_path": "scrapyard.ui.checkbox_radio"
}
### END-PART-META
"""
from __future__ import annotations

import html
from typing import Iterable, Tuple

STATUS = "core"

_ROW_STYLE = (
    "display: flex; align-items: center; gap: var(--space-2);"
    " font-family: var(--font-sans); font-size: var(--text-base);"
    " color: var(--color-text); margin-bottom: var(--space-2);"
)
_INPUT_STYLE = "accent-color: var(--color-primary); width: 1rem; height: 1rem;"
_LEGEND_STYLE = (
    "font-family: var(--font-sans); font-size: var(--text-sm);"
    " font-weight: var(--weight-medium); color: var(--color-text);"
    " margin-bottom: var(--space-2);"
)
_FIELDSET_STYLE = (
    "border: 1px solid var(--color-border); border-radius: var(--radius-sm);"
    " padding: var(--space-3); margin-bottom: var(--space-4);"
)


def _control(kind: str, name: str, value: str, label: str, ident: str,
             checked: bool, disabled: bool) -> str:
    esc = html.escape
    attrs = [
        f'type="{kind}"',
        f'id="{esc(ident, quote=True)}"',
        f'name="{esc(name, quote=True)}"',
        f'value="{esc(str(value), quote=True)}"',
    ]
    if checked:
        attrs.append("checked")
    if disabled:
        attrs.append("disabled")
    attrs.append(f'style="{_INPUT_STYLE}"')
    row = _ROW_STYLE + (" opacity: 0.55;" if disabled else "")
    return (
        f'<label style="{row}">'
        f"<input {' '.join(attrs)}>"
        f"<span>{esc(str(label))}</span>"
        f"</label>"
    )


def render_checkbox(
    name: str,
    label: str,
    *,
    value: str = "on",
    checked: bool = False,
    disabled: bool = False,
) -> str:
    """Return a single labeled checkbox row."""
    return _control("checkbox", name, value, label, name, checked, disabled)


def render_radio_group(
    name: str,
    legend: str,
    options: Iterable[Tuple[str, str]],
    *,
    selected: str | None = None,
    disabled: bool = False,
) -> str:
    """Return a <fieldset> of radios sharing `name`; the option whose value equals
    `selected` is checked."""
    esc = html.escape
    rows = []
    for i, (value, label) in enumerate(options):
        ident = f"{name}-{i}"
        is_sel = selected is not None and str(value) == str(selected)
        rows.append(
            _control("radio", name, value, label, ident, is_sel, disabled)
        )
    return (
        f'<fieldset style="{_FIELDSET_STYLE}">'
        f'<legend style="{_LEGEND_STYLE}">{esc(str(legend))}</legend>'
        f"{''.join(rows)}"
        f"</fieldset>"
    )


def demo() -> str:
    """Sample render: a checked terms checkbox plus a size radio group."""
    return (
        render_checkbox("tos", "I agree to the terms of service", checked=True)
        + render_checkbox("news", "Email me product news")
        + render_radio_group("size", "T-shirt size",
                             [("s", "Small"), ("m", "Medium"), ("l", "Large")],
                             selected="m")
    )


def _selftest() -> None:
    cb = render_checkbox("tos", "I agree", checked=True)
    assert 'type="checkbox"' in cb and 'name="tos"' in cb
    assert " checked" in cb and "accent-color: var(--color-primary)" in cb

    grp = render_radio_group("size", "Size",
                             [("s", "Small"), ("l", "Large")], selected="l")
    assert "<fieldset" in grp and "<legend" in grp
    assert grp.count('type="radio"') == 2
    # exactly the selected option carries the checked attribute
    assert 'value="l" checked' in grp and 'value="s" checked' not in grp

    # ADVERSARIAL: XSS in label, legend and option value/label are escaped
    xss_cb = render_checkbox("<n>", "<script>alert(1)</script>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in xss_cb and "<script>" not in xss_cb
    xss_grp = render_radio_group("g", "<b>legend</b>",
                                 [('"><script>x()</script>', "<i>opt</i>")])
    assert "&lt;b&gt;legend&lt;/b&gt;" in xss_grp
    assert "<script>" not in xss_grp and "<i>opt</i>" not in xss_grp

    print("checkbox_radio selftest OK")


if __name__ == "__main__":
    _selftest()
