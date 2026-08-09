"""
tabs — an accessible tab bar + panels with an inline vanilla-JS switcher.

### PART-META-JSON
{
  "name": "tabs",
  "layer": "ui",
  "purpose": "Render a tabbed interface from a list of {id, label, content}: a role=tablist of buttons and one role=tabpanel per tab, first tab active by default. Switching is handled by a tiny inline vanilla-JS <script> (tabs_script) - no external libraries, no build step, no eval. All panels are present in the markup and remain visible when JS is off, so the content is never lost. Active-tab underline uses var(--color-primary).",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "tabs: list of {id, label, content}; optional group_id for unique element ids.",
  "outputs": "render_tabs(tabs, group_id='tabs') -> tab bar + panels HTML; tabs_script() -> a self-contained <script> that toggles aria-selected/active class + panel visibility.",
  "files_created": [],
  "security_notes": "Tab labels are escaped with html.escape and ids are slugified to [A-Za-z0-9_-] before use in element ids/aria-controls, so untrusted labels or ids cannot break out of attributes. Panel content is a composition slot inserted verbatim and MUST already be valid/escaped HTML by the caller. The script uses getElementById + classList only (no eval, no innerHTML writes).",
  "ai_usage": "html = render_tabs([{'id':'a','label':'Overview','content':'<p>...</p>'}]) ; include tabs_script() once per page (e.g. before </body>).",
  "example": "from scrapyard.ui.tabs import render_tabs, tabs_script; page = render_tabs([{'id':'a','label':'A','content':'<p>A</p>'}]) + tabs_script()",
  "import_path": "scrapyard.ui.tabs"
}
### END-PART-META
"""
from __future__ import annotations

import html
import re
from typing import Dict, List

STATUS = "core"

_SLUG = re.compile(r"[^A-Za-z0-9_-]+")

_TABLIST = ("display:flex;flex-wrap:wrap;gap:var(--space-1);margin:0;padding:0;"
            "border-bottom:1px solid var(--color-border)")
_TAB = ("appearance:none;background:transparent;border:0;cursor:pointer;"
        "font-family:var(--font-sans);font-size:var(--text-sm);"
        "font-weight:var(--weight-medium);color:var(--color-text-muted);"
        "padding:var(--space-3) var(--space-4);"
        "border-bottom:2px solid transparent;margin-bottom:-1px")
_TAB_ACTIVE = ("color:var(--color-text);border-bottom-color:var(--color-primary)")
_PANEL = ("padding:var(--space-4) 0;color:var(--color-text);"
          "font-family:var(--font-sans)")

# Without JS, reveal every panel so no content is hidden.
_NOSCRIPT = '<noscript><style>.sy-tab-panel[hidden]{display:block}</style></noscript>'


def _slug(value: object, fallback: str) -> str:
    s = _SLUG.sub("-", str(value)).strip("-")
    return s or fallback


def render_tabs(tabs: List[Dict[str, str]], *, group_id: str = "tabs") -> str:
    """Render a tab bar and its panels; the first tab is active by default."""
    group = _slug(group_id, "tabs")
    rows = list(tabs or [])

    buttons: List[str] = []
    panels: List[str] = []
    for i, tab in enumerate(rows):
        tid = _slug(tab.get("id", i), f"t{i}")
        tab_id = f"{group}-tab-{tid}"
        panel_id = f"{group}-panel-{tid}"
        label = html.escape(str(tab.get("label", "")))
        active = i == 0
        style = _TAB + (";" + _TAB_ACTIVE if active else "")
        cls = "sy-tab" + (" is-active" if active else "")
        buttons.append(
            f'<button type="button" role="tab" id="{tab_id}" class="{cls}" '
            f'style="{style}" aria-controls="{panel_id}" '
            f'aria-selected="{"true" if active else "false"}" '
            f'tabindex="{"0" if active else "-1"}">{label}</button>'
        )
        panels.append(
            f'<div role="tabpanel" id="{panel_id}" class="sy-tab-panel" '
            f'style="{_PANEL}" aria-labelledby="{tab_id}"'
            f'{"" if active else " hidden"}>{tab.get("content", "")}</div>'
        )

    return (
        f'{_NOSCRIPT}<div class="sy-tabs">'
        f'<div role="tablist" style="{_TABLIST}">{"".join(buttons)}</div>'
        f'{"".join(panels)}</div>'
    )


def tabs_script() -> str:
    """A self-contained inline <script> that wires up every .sy-tabs on the page.

    No external libraries, no build step, no eval. Uses getElementById +
    classList only; toggles aria-selected, the active class, tabindex, and
    each panel's hidden attribute."""
    return (
        "<script>\n"
        "(function(){\n"
        "  function init(root){\n"
        "    var tabs=[].slice.call(root.querySelectorAll('[role=\"tab\"]'));\n"
        "    var panels=[].slice.call(root.querySelectorAll('[role=\"tabpanel\"]'));\n"
        "    function activate(tab){\n"
        "      tabs.forEach(function(t){\n"
        "        var on=t===tab;\n"
        "        t.setAttribute('aria-selected',on?'true':'false');\n"
        "        t.classList.toggle('is-active',on);\n"
        "        t.tabIndex=on?0:-1;\n"
        "        t.style.color=on?'var(--color-text)':'var(--color-text-muted)';\n"
        "        t.style.borderBottomColor=on?'var(--color-primary)':'transparent';\n"
        "      });\n"
        "      panels.forEach(function(p){\n"
        "        p.hidden=p.id!==tab.getAttribute('aria-controls');\n"
        "      });\n"
        "    }\n"
        "    tabs.forEach(function(tab){\n"
        "      tab.addEventListener('click',function(){activate(tab);});\n"
        "      tab.addEventListener('keydown',function(e){\n"
        "        var i=tabs.indexOf(tab),n=tabs.length;\n"
        "        if(e.key==='ArrowRight'){e.preventDefault();tabs[(i+1)%n].focus();}\n"
        "        else if(e.key==='ArrowLeft'){e.preventDefault();tabs[(i-1+n)%n].focus();}\n"
        "      });\n"
        "    });\n"
        "  }\n"
        "  var groups=document.querySelectorAll('.sy-tabs');\n"
        "  [].forEach.call(groups,init);\n"
        "})();\n"
        "</script>"
    )


def demo() -> str:
    """Self-contained sample: three tabs plus the switcher script."""
    markup = render_tabs([
        {"id": "overview", "label": "Overview",
         "content": "<p>A quick summary of the build.</p>"},
        {"id": "logs", "label": "Logs",
         "content": "<pre>step 1 ok\nstep 2 ok</pre>"},
        {"id": "config", "label": "Config",
         "content": "<p>3 regions, 2 replicas.</p>"},
    ], group_id="demo")
    return markup + tabs_script()


def _selftest() -> None:
    out = render_tabs([
        {"id": "a", "label": "Alpha", "content": "<p>A body</p>"},
        {"id": "b", "label": "Beta", "content": "<p>B body</p>"}], group_id="g")
    # tablist + a panel per tab; first active, rest hidden
    assert 'role="tablist"' in out and out.count('role="tabpanel"') == 2
    assert 'aria-selected="true"' in out and 'aria-selected="false"' in out
    assert out.count(" hidden>") == 1  # only the second panel starts hidden
    # active underline uses the primary token; panels present without JS
    assert "var(--color-primary)" in out and _NOSCRIPT in out
    # both panels' content is in the markup (never lost when JS is off)
    assert "<p>A body</p>" in out and "<p>B body</p>" in out
    # aria wiring lines the tab to its panel
    assert 'aria-controls="g-panel-a"' in out and 'id="g-panel-a"' in out
    # script is self-contained, no external libs / eval / innerHTML writes
    js = tabs_script()
    assert js.startswith("<script>") and js.endswith("</script>")
    assert "eval(" not in js and "innerHTML" not in js and "src=" not in js
    assert 'querySelectorAll(\'[role="tab"]\')' in js  # switcher wired by role
    # ADVERSARIAL: label markup escaped; id slugified (no attribute breakout)
    xss = render_tabs([{"id": '"><script>alert(1)</script>',
                        "label": "<script>alert(1)</script>", "content": "x"}])
    assert "<script>alert(1)</script>" not in xss and "&lt;script&gt;" in xss
    assert '"><script>' not in xss
    print("tabs selftest OK")


if __name__ == "__main__":
    _selftest()
