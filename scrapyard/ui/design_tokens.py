"""
design_tokens — the scrapyard's single source of visual truth for UI parts.

### PART-META-JSON
{
  "name": "design_tokens",
  "layer": "ui",
  "purpose": "Design-token foundation for the UI/frontend parts: color/typography/spacing/radius/shadow/z scales plus named themes (bento, keynote, swiss) derived from the factory style bible. Every UI part styles itself from these tokens so an assembled app looks coherent instead of browser-default.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Theme name ('bento'|'keynote'|'swiss'); token category names.",
  "outputs": "get_theme(name) -> full token dict (scales + that theme's colors + mode); list_themes() -> names; SCALES/THEMES data.",
  "files_created": [],
  "security_notes": "Pure static data + dict assembly; no I/O, no eval, no user-controlled code paths. Hex values are validated on access so a malformed theme fails loudly rather than emitting broken CSS downstream.",
  "ai_usage": "t = get_theme('bento'); feed t to ui.theme.render_css_variables to emit :root variables; UI component parts read the same token names.",
  "example": "from scrapyard.ui.design_tokens import get_theme; t = get_theme('swiss'); print(t['color']['primary'])",
  "import_path": "scrapyard.ui.design_tokens"
}
### END-PART-META
"""
from __future__ import annotations

import re
from typing import Dict, List

STATUS = "core"

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# Non-color scales are theme-independent (shared by every theme).
SCALES: Dict[str, Dict[str, str]] = {
    "font": {
        "sans": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        "mono": "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace",
    },
    "text": {  # type scale (rem)
        "xs": "0.75rem", "sm": "0.875rem", "base": "1rem", "lg": "1.125rem",
        "xl": "1.25rem", "2xl": "1.5rem", "3xl": "1.875rem", "4xl": "2.25rem",
    },
    "weight": {"normal": "400", "medium": "500", "semibold": "600", "bold": "700"},
    "leading": {"tight": "1.2", "normal": "1.5", "relaxed": "1.7"},
    "space": {  # 4px base spacing scale
        "0": "0", "1": "0.25rem", "2": "0.5rem", "3": "0.75rem", "4": "1rem",
        "5": "1.5rem", "6": "2rem", "8": "3rem", "10": "4rem", "12": "6rem",
    },
    "radius": {"none": "0", "sm": "4px", "md": "8px", "lg": "16px", "full": "9999px"},
    "shadow": {
        "sm": "0 1px 2px rgba(0,0,0,.12)",
        "md": "0 4px 12px rgba(0,0,0,.18)",
        "lg": "0 12px 32px rgba(0,0,0,.28)",
    },
    "z": {"base": "0", "dropdown": "1000", "sticky": "1100",
          "modal": "1300", "toast": "1400"},
}

# Color themes. Values traced to factory style-bible specs:
#   bento   <- styles/bento-dashboard.md (dark glassmorphic SaaS)
#   keynote <- styles/keynote-gloss.md   (dark minimal, single accent)
#   swiss   <- styles/swiss-international.md (light editorial, one red accent)
# Every theme MUST define the same color keys (enforced by the selftest) so any
# UI part can rely on the full set regardless of which theme a build picks.
THEMES: Dict[str, Dict[str, str]] = {
    "bento": {
        "mode": "dark",
        "base": "#0B0D12", "surface": "#161A23", "border": "#2A3040",
        "primary": "#7C5CFF", "accent": "#38BDF8",
        "success": "#34D399", "warning": "#FBBF24", "danger": "#F87171",
        "text": "#F1F5F9", "text_muted": "#8B93A7",
    },
    "keynote": {
        "mode": "dark",
        "base": "#0A0A0C", "surface": "#141417", "border": "#2A2A30",
        "primary": "#2997FF", "accent": "#0A5FBF",
        "success": "#30D158", "warning": "#FF9F0A", "danger": "#FF453A",
        "text": "#F5F5F7", "text_muted": "#8E8E93",
    },
    "swiss": {
        "mode": "light",
        "base": "#FFFFFF", "surface": "#F5F5F5", "border": "#E5E5E5",
        "primary": "#E30613", "accent": "#005CA9",
        "success": "#0F8A3C", "warning": "#B26A00", "danger": "#C1121F",
        "text": "#0A0A0A", "text_muted": "#6B7280",
    },
}

DEFAULT_THEME = "bento"
_COLOR_KEYS = {k for k in THEMES[DEFAULT_THEME] if k != "mode"}


def list_themes() -> List[str]:
    """Names of the available themes."""
    return sorted(THEMES)


def get_theme(name: str = DEFAULT_THEME) -> Dict[str, object]:
    """Return the full token set for `name`: shared scales + that theme's colors
    + its mode. Raises ValueError for an unknown theme or a malformed hex."""
    if name not in THEMES:
        raise ValueError(f"unknown theme {name!r}; available: {list_themes()}")
    theme = THEMES[name]
    colors = {k: v for k, v in theme.items() if k != "mode"}
    for key, val in colors.items():
        if not _HEX.match(val):
            raise ValueError(f"theme {name!r} color {key!r} is not a #rrggbb hex: {val!r}")
    out: Dict[str, object] = {"name": name, "mode": theme["mode"], "color": colors}
    out.update({cat: dict(vals) for cat, vals in SCALES.items()})
    return out


def _selftest() -> None:
    # every theme resolves and carries valid hex colors
    for name in list_themes():
        t = get_theme(name)
        assert t["name"] == name and t["mode"] in ("dark", "light")
        assert set(t["color"]) == _COLOR_KEYS, f"{name} color keys differ"
        for key, val in t["color"].items():
            assert _HEX.match(val), f"{name}.{key} bad hex {val}"
        # shared scales are present and non-empty
        for cat in ("font", "text", "space", "radius", "shadow", "z", "weight", "leading"):
            assert t[cat] and isinstance(t[cat], dict)

    # all themes expose an IDENTICAL color-key set (so parts can rely on it)
    keysets = [set(get_theme(n)["color"]) for n in list_themes()]
    assert all(ks == keysets[0] for ks in keysets), "themes have divergent color keys"

    # provenance: the derived values match the style-bible specs
    assert THEMES["swiss"]["primary"] == "#E30613"   # Swiss red
    assert THEMES["bento"]["primary"] == "#7C5CFF"    # aurora violet
    assert THEMES["keynote"]["accent"] == "#0A5FBF"   # keynote deep accent

    # ADVERSARIAL: unknown theme + malformed hex both fail loudly, not silently
    for bad in ("nope", "", "BENTO"):
        try:
            get_theme(bad); raise AssertionError(f"unknown theme {bad!r} accepted")
        except ValueError:
            pass
    THEMES["_broken"] = {"mode": "dark", **{k: "red" for k in _COLOR_KEYS}}
    try:
        get_theme("_broken"); raise AssertionError("malformed hex accepted")
    except ValueError:
        pass
    finally:
        del THEMES["_broken"]

    print("design_tokens selftest OK")


if __name__ == "__main__":
    _selftest()
