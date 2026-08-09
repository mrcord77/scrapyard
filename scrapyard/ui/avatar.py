"""
avatar — a user avatar with image or initials fallback and status dot.

### PART-META-JSON
{
  "name": "avatar",
  "layer": "ui",
  "purpose": "Render a circular user avatar: an image when a src is given, otherwise initials derived from the user's name on a themed surface. Supports size presets and an optional presence status dot (online/busy/away/offline). Themed from the design tokens (surface/border/status colors/spacing).",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Keyword args: name (for initials + default alt), src (image URL), size ('sm'|'md'|'lg'|'xl'), status ('online'|'busy'|'away'|'offline'), alt (override).",
  "outputs": "render_avatar(...) -> a <span> HTML string using var(--color-surface)/var(--color-border)/var(--color-success|warning|danger|text-muted)/var(--space-*).",
  "files_created": [],
  "security_notes": "name, alt, and src are escaped with html.escape (src quote-escaped). Initials are computed from the escaped name; unknown size/status inputs fall back to safe defaults rather than being echoed into markup.",
  "ai_usage": "html = render_avatar(name='Ada Lovelace', status='online'); or render_avatar(name='Ada', src='/u/ada.png', size='lg').",
  "example": "from scrapyard.ui.avatar import render_avatar; print(render_avatar(name='Ada Lovelace'))",
  "import_path": "scrapyard.ui.avatar"
}
### END-PART-META
"""
from __future__ import annotations

import html
from typing import Optional

STATUS = "core"

# size preset -> (diameter token, font-size token)
_SIZES = {
    "sm": ("var(--space-6)", "var(--text-xs)"),
    "md": ("var(--space-8)", "var(--text-sm)"),
    "lg": ("var(--space-10)", "var(--text-lg)"),
    "xl": ("var(--space-12)", "var(--text-2xl)"),
}
# status -> presence-dot color token
_STATUS = {
    "online": "var(--color-success)",
    "busy": "var(--color-danger)",
    "away": "var(--color-warning)",
    "offline": "var(--color-text-muted)",
}


def _initials(name: str) -> str:
    words = [w for w in str(name).split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


def render_avatar(*, name: str = "", src: Optional[str] = None, size: str = "md",
                  status: Optional[str] = None, alt: Optional[str] = None) -> str:
    """Render an avatar: image if `src` given, else initials from `name`."""
    diameter, font = _SIZES.get(size, _SIZES["md"])
    label = html.escape(str(alt if alt is not None else name))
    wrap = (f"position:relative;display:inline-flex;width:{diameter};"
            f"height:{diameter};flex:0 0 auto;vertical-align:middle")

    if src:
        inner = (
            f'<img src="{html.escape(str(src), quote=True)}" alt="{label}" '
            f'style="width:{diameter};height:{diameter};border-radius:var(--radius-full);'
            'object-fit:cover;border:1px solid var(--color-border);display:block">'
        )
    else:
        inner = (
            f'<span role="img" aria-label="{label}" '
            f'style="width:{diameter};height:{diameter};border-radius:var(--radius-full);'
            'display:inline-flex;align-items:center;justify-content:center;'
            'background:var(--color-surface);border:1px solid var(--color-border);'
            'color:var(--color-text);font-family:var(--font-sans);'
            f'font-size:{font};font-weight:var(--weight-semibold)">'
            f'{html.escape(_initials(name))}</span>'
        )

    dot = ""
    if status in _STATUS:
        dot = (
            f'<span aria-hidden="true" title="{html.escape(status)}" '
            'style="position:absolute;right:0;bottom:0;width:var(--space-3);'
            'height:var(--space-3);border-radius:var(--radius-full);'
            f'background:{_STATUS[status]};border:2px solid var(--color-base)"></span>'
        )

    return f'<span class="sy-avatar" style="{wrap}">{inner}{dot}</span>'


def demo() -> str:
    """Self-contained sample: an initials avatar and an online image avatar."""
    return (
        render_avatar(name="Ada Lovelace", size="lg", status="online")
        + " "
        + render_avatar(name="Grace Hopper", size="lg")
        + " "
        + render_avatar(name="Alan Turing", size="lg", status="busy")
    )


def _selftest() -> None:
    # initials fallback from a full name
    ini = render_avatar(name="Ada Lovelace", status="online")
    assert ini.startswith('<span class="sy-avatar"') and ">AL<" in ini
    assert "var(--color-surface)" in ini and "var(--color-border)" in ini
    assert "var(--color-success)" in ini  # online dot
    # single-word name -> first two letters
    assert ">GR<" in render_avatar(name="grace")
    # image branch renders an <img>, no initials span
    img = render_avatar(name="Ada", src="/u/ada.png?v=1&s=2", size="xl")
    assert "<img" in img and "&amp;" in img and "var(--space-12)" in img
    # unknown size/status fall back safely (md, no dot)
    fb = render_avatar(name="X Y", size="zzz", status="nope")
    assert "var(--space-8)" in fb and "var(--color-success)" not in fb
    # ADVERSARIAL: script in name is escaped in alt + does not appear live
    xss = render_avatar(name='<script>alert(1)</script>', src="/x.png")
    assert "<script>alert(1)</script>" not in xss and "&lt;script&gt;" in xss
    print("avatar selftest OK")


if __name__ == "__main__":
    _selftest()
