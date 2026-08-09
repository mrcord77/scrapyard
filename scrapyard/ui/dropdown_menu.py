"""
dropdown_menu — a button that toggles a menu, wired by a tiny JS helper.

### PART-META-JSON
{
  "name": "dropdown_menu",
  "layer": "ui",
  "purpose": "Render a dropdown: a trigger button plus a menu of links, with correct ARIA (aria-haspopup, aria-expanded, role=menu/menuitem). A small inline vanilla-JS helper toggles the menu open, closes it on an outside click or ESC, and keeps aria-expanded in sync. Menu is hidden by default; markup is a styled element before JS loads.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "trigger label; a list of items ({'label','href'} or {'label','value'}); optional menu id.",
  "outputs": "dropdown_style()/render_dropdown(label, items, id) -> markup; dropdown_script() -> <script> wiring toggle/outside-click/ESC; demo() -> a menu + script.",
  "files_created": [],
  "security_notes": "Every item label and href is escaped with html.escape before rendering, so an href like javascript:... stays inert text inside the attribute and a <script> label is shown literally. The script toggles a hidden attribute and aria-expanded only — no eval, no innerHTML from user data, no external libraries.",
  "ai_usage": "items=[{'label':'Profile','href':'/me'},{'label':'Sign out','href':'/logout'}]; html = render_dropdown('Account', items); include dropdown_script() once.",
  "example": "render_dropdown('Menu', [{'label':'Edit','href':'#edit'}])",
  "import_path": "scrapyard.ui.dropdown_menu"
}
### END-PART-META
"""
from __future__ import annotations

import html
from typing import Iterable, Mapping

STATUS = "core"

_STYLE_ID = "sy-dropdown-css"
_SCRIPT_ID = "sy-dropdown-js"
_counter = [0]

_STYLE = """\
<style id="%s">
.sy-dd { position: relative; display: inline-block; }
.sy-dd-menu[hidden] { display: none; }
.sy-dd-menu {
  position: absolute; top: calc(100%% + var(--space-1)); left: 0;
  min-width: 180px; z-index: var(--z-dropdown);
  background: var(--color-surface); color: var(--color-text);
  border: 1px solid var(--color-border); border-radius: var(--radius-md);
  box-shadow: var(--shadow-md); padding: var(--space-1); margin: 0; list-style: none;
}
.sy-dd-menu li { margin: 0; }
.sy-dd-item {
  display: block; padding: var(--space-2) var(--space-3);
  color: var(--color-text); text-decoration: none;
  border-radius: var(--radius-sm); font-size: var(--text-sm);
}
.sy-dd-item:hover, .sy-dd-item:focus {
  background: var(--color-base); color: var(--color-primary); text-decoration: none;
}
.sy-dd-caret { margin-left: var(--space-1); font-size: var(--text-xs); }
</style>
""" % _STYLE_ID


def dropdown_style() -> str:
    """The <style> block for dropdowns (id-guarded; include once)."""
    return _STYLE


def render_dropdown(label: str, items: Iterable[Mapping[str, str]],
                    *, menu_id: str | None = None) -> str:
    """A trigger button + a hidden menu of links. `label`, and every item's
    'label' and 'href' (or '#'), are escaped."""
    if menu_id is None:
        _counter[0] += 1
        menu_id = f"sy-dd-{_counter[0]}"
    mid = html.escape(menu_id)
    lis = []
    for it in items:
        text = html.escape(str(it.get("label", "")))
        href = html.escape(str(it.get("href", "#")))
        lis.append(
            f'<li role="none"><a role="menuitem" class="sy-dd-item" '
            f'href="{href}">{text}</a></li>'
        )
    menu = "".join(lis)
    return (
        f'<div class="sy-dd">'
        f'<button type="button" class="sy-dd-trigger" aria-haspopup="true" '
        f'aria-expanded="false" aria-controls="{mid}" data-dd-toggle="{mid}">'
        f'{html.escape(label)}<span class="sy-dd-caret" aria-hidden="true">&#9662;</span>'
        f"</button>"
        f'<ul class="sy-dd-menu" id="{mid}" role="menu" hidden>{menu}</ul>'
        f"</div>"
    )


def dropdown_script() -> str:
    """A <script> wiring the toggle. Idempotent (guarded flag). Outside-click
    and ESC close any open menu and reset aria-expanded. Toggles the [hidden]
    attribute only — no eval, no external libraries."""
    return f"""\
<script id="{_SCRIPT_ID}">
(function () {{
  if (window.__syDropdownWired) return;
  window.__syDropdownWired = true;
  function closeAll(except) {{
    document.querySelectorAll('.sy-dd-menu').forEach(function (m) {{
      if (m === except) return;
      m.hidden = true;
      var t = document.querySelector('[data-dd-toggle="' + m.id + '"]');
      if (t) t.setAttribute('aria-expanded', 'false');
    }});
  }}
  document.addEventListener('click', function (e) {{
    var t = e.target.closest('[data-dd-toggle]');
    if (t) {{
      e.preventDefault();
      var m = document.getElementById(t.getAttribute('data-dd-toggle'));
      if (!m) return;
      var willOpen = m.hidden;
      closeAll(m);
      m.hidden = !willOpen;
      t.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
      return;
    }}
    if (!e.target.closest('.sy-dd-menu')) closeAll(null);
  }});
  document.addEventListener('keydown', function (e) {{
    if (e.key === 'Escape') closeAll(null);
  }});
}})();
</script>"""


def demo() -> str:
    """A styled dropdown plus its wiring script — self-contained."""
    items = [
        {"label": "Profile", "href": "#profile"},
        {"label": "Settings", "href": "#settings"},
        {"label": "Sign out", "href": "#logout"},
    ]
    return (
        dropdown_style()
        + render_dropdown("Account", items, menu_id="sy-demo-dd")
        + dropdown_script()
    )


def _selftest() -> None:
    assert _STYLE_ID in dropdown_style() and "var(--z-dropdown)" in dropdown_style()

    dd = render_dropdown("Account", [{"label": "Edit", "href": "/edit"}], menu_id="dd1")
    assert 'aria-haspopup="true"' in dd and 'aria-expanded="false"' in dd
    assert 'role="menu"' in dd and 'role="menuitem"' in dd
    assert 'data-dd-toggle="dd1"' in dd and ' hidden>' in dd
    assert 'href="/edit"' in dd and "Edit" in dd

    scr = dropdown_script()
    assert scr.startswith("<script") and _SCRIPT_ID in scr
    assert "Escape" in scr and "aria-expanded" in scr
    assert "eval(" not in scr and "__syDropdownWired" in scr  # no eval, idempotent

    assert "sy-dd" in demo() and "data-dd-toggle" in demo()

    # ADVERSARIAL (XSS): a script label and a javascript: href are escaped
    evil = render_dropdown(
        "<script>alert(1)</script>",
        [{"label": "<img onerror=x>", "href": 'javascript:alert(1)"'}],
        menu_id="dd2",
    )
    assert "<script>alert(1)</script>" not in evil
    assert "<img onerror=x>" not in evil
    assert "&lt;script&gt;" in evil and "&lt;img" in evil
    # the quote in the href is entity-escaped, so it cannot break the attribute
    assert 'href="javascript:alert(1)&quot;"' in evil

    print("dropdown_menu selftest OK")


if __name__ == "__main__":
    _selftest()
