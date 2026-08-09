"""
theme — emit CSS custom properties from the design tokens.

### PART-META-JSON
{
  "name": "theme",
  "layer": "ui",
  "purpose": "Render a design-token theme to CSS custom properties (:root variables) that every UI/frontend part references, plus a data-theme selector block so a page can switch themes. Turns the design_tokens data into drop-in CSS.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Theme name(s) from ui.design_tokens; optional selector.",
  "outputs": "render_css_variables(theme) -> ':root{--...}' CSS string; render_all_themes() -> default :root + [data-theme] blocks; variable name helpers.",
  "files_created": [],
  "security_notes": "Token values come only from ui.design_tokens (static, hex-validated) — no user input reaches the CSS. If a caller ever passes untrusted token values, they must validate them first; this part assumes trusted tokens.",
  "ai_usage": "css = render_css_variables('bento'); put it in a <style> tag; components use var(--color-primary) etc. render_all_themes() for a theme-switchable page.",
  "example": "from scrapyard.ui.theme import render_css_variables; print(render_css_variables('bento'))",
  "import_path": "scrapyard.ui.theme"
}
### END-PART-META
"""
from __future__ import annotations

from typing import Dict, List

from scrapyard.ui.design_tokens import DEFAULT_THEME, get_theme, list_themes

STATUS = "core"

# token category -> CSS variable prefix
_PREFIX = {
    "color": "color", "font": "font", "text": "text", "weight": "weight",
    "leading": "leading", "space": "space", "radius": "radius",
    "shadow": "shadow", "z": "z",
}


def _vname(prefix: str, key: str) -> str:
    # CSS custom-property names use hyphens; token keys may use underscores
    # (e.g. text_muted -> --color-text-muted).
    return f"--{prefix}-{key.replace('_', '-')}"


def var_names(theme: str = DEFAULT_THEME) -> List[str]:
    """Every CSS variable name a theme defines, e.g. '--color-primary'."""
    t = get_theme(theme)
    names: List[str] = []
    for cat, prefix in _PREFIX.items():
        for key in t[cat]:  # type: ignore[index]
            names.append(_vname(prefix, key))
    return names


def _declarations(theme: str) -> List[str]:
    t = get_theme(theme)
    decls: List[str] = []
    for cat, prefix in _PREFIX.items():
        for key, val in t[cat].items():  # type: ignore[union-attr]
            decls.append(f"  {_vname(prefix, key)}: {val};")
    return decls


def render_css_variables(theme: str = DEFAULT_THEME, selector: str = ":root") -> str:
    """Render one theme as a CSS rule of custom properties under `selector`."""
    body = "\n".join(_declarations(theme))
    return f"{selector} {{\n{body}\n}}\n"


def render_all_themes(default: str = DEFAULT_THEME) -> str:
    """Default theme on :root, every theme also under [data-theme="name"] so a
    page can switch by setting the attribute on <html>."""
    blocks = [render_css_variables(default, ":root")]
    for name in list_themes():
        blocks.append(render_css_variables(name, f'[data-theme="{name}"]'))
    return "\n".join(blocks)


def _selftest() -> None:
    css = render_css_variables("bento")
    assert css.startswith(":root {") and css.rstrip().endswith("}")
    # real, referenceable variables with the derived values
    assert "--color-primary: #7C5CFF;" in css
    assert "--space-4: 1rem;" in css
    assert "--radius-md: 8px;" in css
    assert "--font-sans:" in css

    # every declared var name actually appears in the emitted CSS
    for name in var_names("bento"):
        assert f"{name}:" in css, f"{name} declared but not emitted"

    # custom selector honored
    scoped = render_css_variables("swiss", ".card")
    assert scoped.startswith(".card {") and "--color-primary: #E30613;" in scoped

    # all-themes bundle: default :root + one data-theme block per theme
    allc = render_all_themes("bento")
    assert ":root {" in allc
    for name in list_themes():
        assert f'[data-theme="{name}"] {{' in allc
    # bento and swiss primaries differ in the bundle (themes are distinct)
    assert "#7C5CFF" in allc and "#E30613" in allc

    # ADVERSARIAL: an unknown theme must raise, not emit empty/garbage CSS
    try:
        render_css_variables("nonexistent"); raise AssertionError("unknown theme rendered")
    except ValueError:
        pass

    print("theme selftest OK")


if __name__ == "__main__":
    _selftest()
