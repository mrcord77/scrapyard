"""
css_baseline — reset + base element styles built on the theme variables.

### PART-META-JSON
{
  "name": "css_baseline",
  "layer": "ui",
  "purpose": "A small CSS reset plus base element styling (body, headings, links, form controls, tables, code) that references the ui.theme custom properties, so the existing frontend HTML parts render as an intentional, themed page instead of browser-default. Theme-agnostic: it adapts to whatever :root variables are applied.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "None (optional: include_theme to bundle a theme's variables).",
  "outputs": "render_baseline_css() -> reset+base CSS string using var(--...); render_document(body, theme) -> a full themed HTML document wrapping given body HTML.",
  "files_created": [],
  "security_notes": "render_baseline_css emits only static CSS referencing token variables (no user input). render_document escapes the page <title>; the body HTML is inserted verbatim and MUST already be escaped by the frontend part that produced it (all scrapyard.frontend parts escape their inputs).",
  "ai_usage": "page = render_document(forms.render_form(...), theme='bento'); serve as text/html. Or drop render_baseline_css() into a <style> next to render_css_variables().",
  "example": "from scrapyard.ui.css_baseline import render_document; html = render_document('<h1>Hi</h1>', theme='swiss')",
  "import_path": "scrapyard.ui.css_baseline"
}
### END-PART-META
"""
from __future__ import annotations

import html

from scrapyard.ui.design_tokens import DEFAULT_THEME, get_theme
from scrapyard.ui.theme import render_css_variables

STATUS = "core"

_BASELINE = """\
*, *::before, *::after { box-sizing: border-box; }
* { margin: 0; }
html { -webkit-text-size-adjust: 100%; }
body {
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  color: var(--color-text);
  background: var(--color-base);
  padding: var(--space-5);
}
h1, h2, h3, h4 { line-height: var(--leading-tight); font-weight: var(--weight-semibold); }
h1 { font-size: var(--text-3xl); } h2 { font-size: var(--text-2xl); }
h3 { font-size: var(--text-xl); } h4 { font-size: var(--text-lg); }
p, ul, ol, table, form { margin-block: var(--space-3); }
a { color: var(--color-primary); text-decoration: none; }
a:hover { text-decoration: underline; }
small, .muted { color: var(--color-text-muted); }
code, pre { font-family: var(--font-mono); font-size: var(--text-sm); }
pre { background: var(--color-surface); padding: var(--space-3); border-radius: var(--radius-md); overflow-x: auto; }

label { display: block; font-size: var(--text-sm); color: var(--color-text-muted); margin-bottom: var(--space-1); }
input, select, textarea {
  font: inherit; color: var(--color-text); background: var(--color-surface);
  border: 1px solid var(--color-border); border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3); width: 100%;
}
input:focus, select:focus, textarea:focus { outline: 2px solid var(--color-primary); outline-offset: 1px; }
button, .btn {
  font: inherit; font-weight: var(--weight-medium); cursor: pointer;
  color: #fff; background: var(--color-primary);
  border: 0; border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-4);
}
button:hover, .btn:hover { filter: brightness(1.08); }
.error { color: var(--color-danger); font-size: var(--text-sm); display: block; }

table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-border); }
th { color: var(--color-text-muted); font-weight: var(--weight-semibold); }

.card {
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); padding: var(--space-5); box-shadow: var(--shadow-md);
}
"""


def render_baseline_css() -> str:
    """The reset + base element CSS (references var(--...); theme-agnostic)."""
    return _BASELINE


def render_document(body_html: str, *, theme: str = DEFAULT_THEME,
                    title: str = "App", lang: str = "en") -> str:
    """Wrap already-escaped body HTML in a full themed HTML document: doctype,
    the theme's CSS variables, the baseline stylesheet, and the body."""
    mode = get_theme(theme)["mode"]
    style = render_css_variables(theme) + "\n" + render_baseline_css()
    return (
        f"<!doctype html>\n"
        f'<html lang="{html.escape(lang)}" data-theme="{html.escape(theme)}" '
        f'style="color-scheme: {mode}">\n'
        f"<head>\n<meta charset=\"utf-8\">\n"
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>\n{style}</style>\n</head>\n"
        f"<body>\n{body_html}\n</body>\n</html>\n"
    )


def _selftest() -> None:
    css = render_baseline_css()
    # references token variables (not hardcoded colors) so it adapts to any theme
    assert "var(--color-text)" in css and "var(--color-base)" in css
    assert "var(--space-" in css and "var(--radius-" in css
    # no raw hex leaked into the baseline (it must be theme-driven)
    import re
    assert not re.search(r"#[0-9a-fA-F]{6}", css.replace("#fff", "")), "baseline hardcodes a color"
    # every var(--x) the baseline references must be a DEFINED token (no danglers)
    from scrapyard.ui.theme import var_names
    defined = set(var_names())
    refs = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", css))
    dangling = [v for v in refs if v not in defined]
    assert not dangling, f"baseline references undefined tokens: {dangling}"

    # full document: doctype, theme vars inlined, baseline, body present
    doc = render_document("<h1>Dashboard</h1>", theme="bento", title="Home")
    assert doc.startswith("<!doctype html>")
    assert 'data-theme="bento"' in doc and "color-scheme: dark" in doc
    assert "--color-primary: #7C5CFF;" in doc            # theme vars inlined
    assert "var(--color-text)" in doc                    # baseline included
    assert "<h1>Dashboard</h1>" in doc                   # body inserted
    assert "<title>Home</title>" in doc

    # swiss is a light theme -> color-scheme light
    assert "color-scheme: light" in render_document("x", theme="swiss")

    # ADVERSARIAL: the page <title> is escaped
    doc2 = render_document("<p>ok</p>", title="<script>alert(1)</script>")
    assert "<title><script>" not in doc2 and "&lt;script&gt;" in doc2

    # unknown theme fails loudly
    try:
        render_document("x", theme="nope"); raise AssertionError("unknown theme rendered")
    except ValueError:
        pass

    print("css_baseline selftest OK")


if __name__ == "__main__":
    _selftest()
