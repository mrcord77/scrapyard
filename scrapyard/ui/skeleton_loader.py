"""
skeleton_loader — shimmering placeholder blocks for loading states.

### PART-META-JSON
{
  "name": "skeleton_loader",
  "layer": "ui",
  "purpose": "Render animated skeleton placeholders (line, avatar, and card shapes) that shimmer while real content loads. The shimmer is a pure-CSS keyframe over token colors, so it needs no JavaScript and adapts to the active theme.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "shape ('line'|'avatar'|'card'); optional width/size hints; line count for multi-line blocks.",
  "outputs": "skeleton_css() -> <style> with the shimmer keyframe; render_skeleton(shape, ...) -> placeholder HTML; render_card_skeleton() -> avatar+lines composite; demo() -> gallery.",
  "files_created": [],
  "security_notes": "Width/size hints are coerced to a safe numeric+unit form (via html.escape and a numeric guard) before entering inline CSS, so a caller cannot break out of the style attribute or inject markup. No caller text is rendered as HTML content.",
  "ai_usage": "from scrapyard.ui.skeleton_loader import skeleton_css, render_skeleton; page = skeleton_css() + render_skeleton('card')",
  "example": "render_skeleton('line', width='60%')",
  "import_path": "scrapyard.ui.skeleton_loader"
}
### END-PART-META
"""
from __future__ import annotations

import html

STATUS = "core"

_CSS_ID = "sy-skeleton-css"

# The shimmer sweeps a gradient built from theme tokens across each block.
_STYLE = """\
<style id="__ID__">
@keyframes sy-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
.sy-skel {
  background: linear-gradient(90deg,
    var(--color-surface) 25%, var(--color-border) 50%, var(--color-surface) 75%);
  background-size: 200% 100%;
  animation: sy-shimmer 1.4s ease-in-out infinite;
  border-radius: var(--radius-sm);
  display: block;
}
@media (prefers-reduced-motion: reduce) { .sy-skel { animation: none; } }
.sy-skel-avatar { border-radius: var(--radius-full); }
.sy-skel-card {
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); padding: var(--space-4);
  display: flex; flex-direction: column; gap: var(--space-3);
}
</style>
""".replace("__ID__", _CSS_ID)


def skeleton_css() -> str:
    """The <style> block (with the shimmer @keyframes). Include once per page;
    it is id-guarded so duplicates are harmless."""
    return _STYLE


def _dim(value: str | int, fallback: str) -> str:
    """Coerce a width/size hint to a safe CSS length. Accepts an int (px) or a
    string of digits optionally followed by px/%/rem/em; anything else falls
    back. The result is escaped so it can never break the style attribute."""
    if isinstance(value, int):
        return f"{value}px"
    s = str(value).strip()
    if s.endswith("%"):
        core, suffix = s[:-1], "%"
    else:
        core = s
        for u in ("px", "rem", "em"):
            if s.endswith(u):
                core, suffix = s[: -len(u)], u
                break
        else:
            suffix = ""
    try:
        float(core)
    except ValueError:
        return fallback
    if not suffix:
        suffix = "px"
    return html.escape(f"{core}{suffix}")


def render_skeleton(shape: str = "line", *, width: str | int = "100%",
                    height: str | int | None = None) -> str:
    """A single placeholder. `shape` is 'line', 'avatar', or 'card'."""
    if shape == "avatar":
        size = _dim(width if height is None else height, "40px")
        style = f"width:{size};height:{size}"
        return f'<span class="sy-skel sy-skel-avatar" style="{style}" aria-hidden="true"></span>'
    if shape == "card":
        return render_card_skeleton()
    w = _dim(width, "100%")
    h = _dim(height if height is not None else "0.9rem", "0.9rem")
    style = f"width:{w};height:{h};margin-block:var(--space-1)"
    return f'<span class="sy-skel" style="{style}" aria-hidden="true"></span>'


def render_card_skeleton(*, lines: int = 3) -> str:
    """An avatar + a stack of lines inside a themed card placeholder."""
    try:
        n = max(1, int(lines))
    except (TypeError, ValueError):
        n = 3
    rows = [
        '<div style="display:flex;gap:var(--space-3);align-items:center">'
        + render_skeleton("avatar", width="44px")
        + '<span class="sy-skel" style="width:40%;height:0.9rem"></span></div>'
    ]
    for i in range(n):
        w = "90%" if i < n - 1 else "60%"
        rows.append(render_skeleton("line", width=w))
    body = "".join(rows)
    return (
        '<div class="sy-skel-card" role="status" aria-label="Loading">'
        f"{body}</div>"
    )


def demo() -> str:
    """The stylesheet plus a gallery of shapes."""
    lines = "".join(
        render_skeleton("line", width=w) for w in ("100%", "85%", "70%")
    )
    return (
        skeleton_css()
        + '<div style="display:flex;flex-direction:column;gap:var(--space-4);max-width:420px">'
        + f'<div style="display:flex;flex-direction:column;gap:var(--space-1)">{lines}</div>'
        + render_skeleton("avatar", width="56px")
        + render_card_skeleton(lines=3)
        + "</div>"
    )


def _selftest() -> None:
    css = skeleton_css()
    assert "@keyframes sy-shimmer" in css and _CSS_ID in css
    assert "var(--color-surface)" in css and "var(--color-border)" in css  # token-driven

    line = render_skeleton("line", width="60%")
    assert "sy-skel" in line and "width:60%" in line

    avatar = render_skeleton("avatar", width="48px")
    assert "sy-skel-avatar" in avatar and "48px" in avatar

    card = render_card_skeleton(lines=2)
    assert "sy-skel-card" in card and 'role="status"' in card

    # demo composes with its stylesheet
    d = demo()
    assert "@keyframes" in d and "sy-skel-card" in d

    # ADVERSARIAL (XSS): a script payload in a size hint cannot escape the
    # style attribute or inject markup — it is rejected to the fallback.
    evil = render_skeleton("line", width='"><script>alert(1)</script>')
    assert "<script>" not in evil
    assert 'width:100%' in evil  # fell back to the safe default

    # a valid percentage passes; a bogus unit falls back
    assert "width:33%" in render_skeleton("line", width="33%")
    assert "width:100%" in render_skeleton("line", width="12zz")

    print("skeleton_loader selftest OK")


if __name__ == "__main__":
    _selftest()
