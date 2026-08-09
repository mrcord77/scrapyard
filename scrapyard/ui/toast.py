"""
toast — transient notification stack with a JS push helper.

### PART-META-JSON
{
  "name": "toast",
  "layer": "ui",
  "purpose": "Render a stacked toast notification system: a fixed container, a static toast element for server-rendered messages, and a small inline vanilla-JS helper (window.syToast) that pushes transient toasts which auto-dismiss. Progressive enhancement — server-rendered toasts show without JS; the script adds dynamic push + timed removal.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "message text; variant ('info'|'success'|'warning'|'danger'); optional container position; auto-dismiss timeout (ms) for the JS helper.",
  "outputs": "toast_style()/toast_container()/render_toast(message,variant) -> markup; toast_script() -> <script> defining window.syToast(message,variant,ms); demo() -> container + script + trigger.",
  "files_created": [],
  "security_notes": "render_toast escapes the message with html.escape so server-side markup cannot execute. The JS helper assigns message text via textContent (never innerHTML), so runtime pushes are also XSS-safe. The script uses no eval and no external libraries; it only creates nodes and toggles classes.",
  "ai_usage": "Include toast_style()+toast_container()+toast_script() once; then call syToast('Saved','success') from your own event handlers, or emit render_toast(...) server-side.",
  "example": "from scrapyard.ui.toast import render_toast; html = render_toast('Saved', variant='success')",
  "import_path": "scrapyard.ui.toast"
}
### END-PART-META
"""
from __future__ import annotations

import html

STATUS = "core"

_STYLE_ID = "sy-toast-css"
_SCRIPT_ID = "sy-toast-js"
_ROOT_ID = "sy-toast-root"

_VARIANT = {
    "info": "--color-accent",
    "success": "--color-success",
    "warning": "--color-warning",
    "danger": "--color-danger",
}

_STYLE = """\
<style id="%s">
#%s {
  position: fixed; bottom: var(--space-4); right: var(--space-4);
  display: flex; flex-direction: column; gap: var(--space-2);
  z-index: var(--z-toast); max-width: min(360px, calc(100vw - var(--space-8)));
}
.sy-toast {
  display: flex; align-items: flex-start; gap: var(--space-2);
  background: var(--color-surface); color: var(--color-text);
  border: 1px solid var(--color-border); border-left: 4px solid var(--color-accent);
  border-radius: var(--radius-md); box-shadow: var(--shadow-lg);
  padding: var(--space-3) var(--space-4); font-size: var(--text-sm);
  line-height: var(--leading-normal);
  opacity: 1; transform: translateY(0); transition: opacity .25s ease, transform .25s ease;
}
.sy-toast.sy-toast-hide { opacity: 0; transform: translateY(var(--space-2)); }
.sy-toast-success { border-left-color: var(--color-success); }
.sy-toast-warning { border-left-color: var(--color-warning); }
.sy-toast-danger  { border-left-color: var(--color-danger); }
.sy-toast-close {
  background: transparent; border: 0; cursor: pointer; padding: 0 var(--space-1);
  color: var(--color-text-muted); font-size: var(--text-lg); line-height: 1;
}
@media (prefers-reduced-motion: reduce) { .sy-toast { transition: none; } }
</style>
""" % (_STYLE_ID, _ROOT_ID)


def toast_style() -> str:
    """The <style> block for toasts (id-guarded; include once)."""
    return _STYLE


def toast_container(*, root_id: str = _ROOT_ID) -> str:
    """The fixed stacking container the toasts render into."""
    rid = html.escape(root_id)
    return (f'<div id="{rid}" class="sy-toast-root" role="region" '
            f'aria-live="polite" aria-label="Notifications"></div>')


def render_toast(message: str, *, variant: str = "info") -> str:
    """A single server-rendered toast element (shows without JS). Escaped."""
    variant = variant if variant in _VARIANT else "info"
    return (
        f'<div class="sy-toast sy-toast-{html.escape(variant)}" role="status">'
        f'<span style="flex:1;min-width:0">{html.escape(message)}</span>'
        f'<button type="button" class="sy-toast-close" aria-label="Dismiss" '
        f"onclick=\"this.closest('.sy-toast').remove()\">&times;</button>"
        f"</div>"
    )


def toast_script(*, root_id: str = _ROOT_ID) -> str:
    """A <script> defining window.syToast(message, variant, ms). Idempotent:
    guarded on window.syToast so including it twice is safe. No eval, no deps —
    it creates nodes, sets textContent, and toggles a hide class on a timer."""
    rid = html.escape(root_id)
    return f"""\
<script id="{_SCRIPT_ID}">
(function () {{
  if (window.syToast) return;
  var ROOT_ID = {rid!r};
  function root() {{
    var r = document.getElementById(ROOT_ID);
    if (!r) {{
      r = document.createElement('div');
      r.id = ROOT_ID; r.className = 'sy-toast-root';
      r.setAttribute('role', 'region'); r.setAttribute('aria-live', 'polite');
      document.body.appendChild(r);
    }}
    return r;
  }}
  function remove(el) {{
    el.classList.add('sy-toast-hide');
    setTimeout(function () {{ if (el.parentNode) el.parentNode.removeChild(el); }}, 260);
  }}
  window.syToast = function (message, variant, ms) {{
    var ok = {{info:1, success:1, warning:1, danger:1}};
    variant = ok[variant] ? variant : 'info';
    var el = document.createElement('div');
    el.className = 'sy-toast sy-toast-' + variant;
    el.setAttribute('role', 'status');
    var span = document.createElement('span');
    span.style.flex = '1'; span.style.minWidth = '0';
    span.textContent = String(message == null ? '' : message);
    var btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'sy-toast-close';
    btn.setAttribute('aria-label', 'Dismiss'); btn.innerHTML = '&times;';
    btn.addEventListener('click', function () {{ remove(el); }});
    el.appendChild(span); el.appendChild(btn);
    root().appendChild(el);
    var timeout = typeof ms === 'number' ? ms : 4000;
    if (timeout > 0) setTimeout(function () {{ remove(el); }}, timeout);
    return el;
  }};
}})();
</script>"""


def demo() -> str:
    """Style + container + script + a trigger button, self-contained."""
    trigger = (
        '<button type="button" onclick="syToast(\'Changes saved.\',\'success\')" '
        'style="margin-bottom:var(--space-3)">Show a toast</button>'
    )
    return (
        toast_style()
        + trigger
        + toast_container()
        + render_toast("A server-rendered toast (visible without JS).", variant="info")
        + toast_script()
    )


def _selftest() -> None:
    assert "@keyframes" not in toast_style()  # sanity: style is scoped, not global keyframes
    assert _STYLE_ID in toast_style() and "var(--z-toast)" in toast_style()

    cont = toast_container()
    assert _ROOT_ID in cont and 'aria-live="polite"' in cont

    t = render_toast("Saved", variant="success")
    assert "sy-toast-success" in t and "Saved" in t

    scr = toast_script()
    assert scr.startswith("<script") and _SCRIPT_ID in scr
    assert "window.syToast" in scr and "textContent" in scr
    assert "eval(" not in scr and "http" not in scr  # no eval, no external deps
    assert "if (window.syToast) return;" in scr       # idempotent guard

    assert "sy-toast" in demo() and "syToast(" in demo()

    # ADVERSARIAL (XSS): a <script> payload in a server toast is escaped, not raw
    evil = render_toast("<script>alert(1)</script>", variant="danger")
    assert "<script>alert(1)</script>" not in evil and "&lt;script&gt;" in evil

    print("toast selftest OK")


if __name__ == "__main__":
    _selftest()
