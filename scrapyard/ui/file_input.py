"""
file_input — a labeled, themed file-upload input primitive.

### PART-META-JSON
{
  "name": "file_input",
  "layer": "ui",
  "purpose": "Render a labeled <input type=file> with an accept filter, optional multiple selection, a required marker and help text, styled entirely from design tokens so the upload control matches any theme.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "name; label; accept string (e.g. 'image/*,.pdf'); multiple bool; required bool; help text.",
  "outputs": "render_file_input(...) -> a labeled file input block as an HTML string; demo() -> str sample.",
  "files_created": [],
  "security_notes": "name, label, accept and help are escaped with html.escape, so an XSS payload such as <script> in any of them becomes &lt;script&gt; and cannot execute. Styling is token-only via var(--color-*) with no raw color literals.",
  "ai_usage": "from scrapyard.ui.file_input import render_file_input; html = render_file_input('avatar', 'Avatar', accept='image/*')",
  "example": "render_file_input('docs', 'Documents', accept='.pdf', multiple=True)",
  "import_path": "scrapyard.ui.file_input"
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
    "width: 100%; font-family: var(--font-sans); font-size: var(--text-sm);"
    " color: var(--color-text-muted); background: var(--color-surface);"
    " border: 1px dashed var(--color-border); border-radius: var(--radius-md);"
    " padding: var(--space-3); cursor: pointer;"
)
_HELP_STYLE = (
    "display: block; font-size: var(--text-xs); color: var(--color-text-muted);"
    " margin-top: var(--space-1);"
)


def render_file_input(
    name: str,
    label: str,
    *,
    accept: str = "",
    multiple: bool = False,
    required: bool = False,
    help: str = "",
) -> str:
    """Return a labeled file-upload block. `accept` sets the browser file filter;
    `multiple` allows selecting several files."""
    esc = html.escape
    nm = esc(name, quote=True)
    req_mark = (
        ' <span style="color: var(--color-danger);" aria-hidden="true">*</span>'
        if required else ""
    )
    attrs = [f'id="{nm}"', f'name="{nm}"', 'type="file"']
    if accept:
        attrs.append(f'accept="{esc(accept, quote=True)}"')
    if multiple:
        attrs.append("multiple")
    if required:
        attrs.append("required")
    attrs.append(f'style="{_CONTROL_STYLE}"')

    out = [
        '<div style="margin-bottom: var(--space-4);">',
        f'<label for="{nm}" style="{_LABEL_STYLE}">{esc(label)}{req_mark}</label>',
        f"<input {' '.join(attrs)}>",
    ]
    if help:
        out.append(f'<small style="{_HELP_STYLE}">{esc(help)}</small>')
    out.append("</div>")
    return "".join(out)


def demo() -> str:
    """Sample render: an avatar image picker and a multi-file document upload."""
    return (
        render_file_input("avatar", "Profile photo", accept="image/*",
                          help="PNG or JPG, up to 5 MB.")
        + render_file_input("docs", "Supporting documents", accept=".pdf,.docx",
                            multiple=True, required=True,
                            help="Attach one or more PDF/DOCX files.")
    )


def _selftest() -> None:
    fi = render_file_input("avatar", "Avatar", accept="image/*", help="JPG/PNG")
    assert '<label for="avatar"' in fi and 'type="file"' in fi
    assert 'accept="image/*"' in fi and "JPG/PNG" in fi
    assert "var(--color-border)" in fi and "border-radius: var(--radius-md)" in fi

    # multiple + required attributes present when requested
    multi = render_file_input("d", "Docs", multiple=True, required=True)
    assert " multiple" in multi and " required" in multi

    # ADVERSARIAL: XSS in label, accept and help are escaped, never raw
    xss = render_file_input("<n>", "<script>alert(1)</script>",
                            accept='"><script>x()</script>',
                            help="<b>hint</b>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in xss
    assert "<script>" not in xss and "<b>hint</b>" not in xss

    print("file_input selftest OK")


if __name__ == "__main__":
    _selftest()
