"""
modal — accessible dialog with backdrop, opened/closed by a tiny JS helper.

### PART-META-JSON
{
  "name": "modal",
  "layer": "ui",
  "purpose": "Render an accessible modal dialog (role=dialog, aria-modal, aria-labelledby) with a dimmed backdrop, plus open/close triggers wired by a small inline vanilla-JS helper. Buttons carrying data-modal-open / data-modal-close toggle the dialog; ESC and a backdrop click also close it. Hidden by default, so nothing shows until opened.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "modal id; title; body HTML (caller-escaped); optional footer HTML; open-trigger label.",
  "outputs": "modal_style()/render_modal(...)/open_button(...) -> markup; modal_script() -> <script> wiring open/close/ESC/backdrop; demo() -> a button + dialog + script.",
  "files_created": [],
  "security_notes": "The dialog title is escaped with html.escape. The body/footer HTML is inserted verbatim and MUST already be escaped by the caller (same contract as css_baseline.render_document). The script toggles the [hidden] attribute and an aria flag only — no eval, no innerHTML from user data, no external libraries.",
  "ai_usage": "html = open_button('Open', target='m1') + render_modal('m1','Title','<p>Body</p>'); include modal_script() once.",
  "example": "from scrapyard.ui.modal import render_modal; render_modal('m1', 'Confirm', '<p>Sure?</p>')",
  "import_path": "scrapyard.ui.modal"
}
### END-PART-META
"""
from __future__ import annotations

import html

STATUS = "core"

_STYLE_ID = "sy-modal-css"
_SCRIPT_ID = "sy-modal-js"

_STYLE = """\
<style id="%s">
.sy-modal[hidden] { display: none; }
.sy-modal {
  position: fixed; inset: 0; z-index: var(--z-modal);
  display: flex; align-items: center; justify-content: center;
  padding: var(--space-4);
}
.sy-modal-backdrop {
  position: absolute; inset: 0; background: rgba(0,0,0,.55);
}
.sy-modal-dialog {
  position: relative; z-index: 1; width: min(520px, 100%%);
  max-height: calc(100vh - var(--space-8)); overflow: auto;
  background: var(--color-surface); color: var(--color-text);
  border: 1px solid var(--color-border); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg); padding: var(--space-5);
}
.sy-modal-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: var(--space-3); margin-bottom: var(--space-3);
}
.sy-modal-title { font-size: var(--text-xl); font-weight: var(--weight-semibold); }
.sy-modal-close {
  background: transparent; border: 0; cursor: pointer; padding: 0 var(--space-1);
  color: var(--color-text-muted); font-size: var(--text-2xl); line-height: 1;
}
.sy-modal-foot {
  display: flex; justify-content: flex-end; gap: var(--space-2);
  margin-top: var(--space-4);
}
</style>
""" % _STYLE_ID


def modal_style() -> str:
    """The <style> block for modals (id-guarded; include once)."""
    return _STYLE


def open_button(label: str, *, target: str, **_ignore) -> str:
    """A button that opens the modal whose id is `target`."""
    return (f'<button type="button" data-modal-open="{html.escape(target)}">'
            f"{html.escape(label)}</button>")


def render_modal(modal_id: str, title: str, body_html: str,
                 *, footer_html: str | None = None) -> str:
    """A hidden, accessible dialog. `title` is escaped; `body_html`/`footer_html`
    are inserted verbatim and must already be escaped by the caller."""
    mid = html.escape(modal_id)
    title_id = f"{mid}-title"
    default_foot = (
        f'<button type="button" data-modal-close="{mid}">Close</button>'
    )
    foot = footer_html if footer_html is not None else default_foot
    return (
        f'<div class="sy-modal" id="{mid}" role="dialog" aria-modal="true" '
        f'aria-labelledby="{title_id}" hidden>'
        f'<div class="sy-modal-backdrop" data-modal-close="{mid}"></div>'
        f'<div class="sy-modal-dialog">'
        f'<div class="sy-modal-head">'
        f'<h2 class="sy-modal-title" id="{title_id}">{html.escape(title)}</h2>'
        f'<button type="button" class="sy-modal-close" aria-label="Close" '
        f'data-modal-close="{mid}">&times;</button>'
        f"</div>"
        f'<div class="sy-modal-body">{body_html}</div>'
        f'<div class="sy-modal-foot">{foot}</div>'
        f"</div></div>"
    )


def modal_script() -> str:
    """A <script> wiring open/close. Idempotent (guarded flag). ESC closes the
    top-most open dialog; a click on the backdrop or any [data-modal-close]
    closes it. Toggles the [hidden] attribute only — no eval, no libraries."""
    return f"""\
<script id="{_SCRIPT_ID}">
(function () {{
  if (window.__syModalWired) return;
  window.__syModalWired = true;
  function openModal(id) {{
    var m = document.getElementById(id);
    if (m) {{ m.hidden = false; m.setAttribute('aria-hidden', 'false'); }}
  }}
  function closeModal(m) {{
    if (m) {{ m.hidden = true; m.setAttribute('aria-hidden', 'true'); }}
  }}
  document.addEventListener('click', function (e) {{
    var o = e.target.closest('[data-modal-open]');
    if (o) {{ e.preventDefault(); openModal(o.getAttribute('data-modal-open')); return; }}
    var c = e.target.closest('[data-modal-close]');
    if (c) {{ e.preventDefault(); closeModal(document.getElementById(c.getAttribute('data-modal-close'))); }}
  }});
  document.addEventListener('keydown', function (e) {{
    if (e.key !== 'Escape') return;
    var open = document.querySelectorAll('.sy-modal:not([hidden])');
    if (open.length) closeModal(open[open.length - 1]);
  }});
}})();
</script>"""


def demo() -> str:
    """A trigger button, a dialog, and the wiring script — self-contained."""
    body = ("<p>This dialog is hidden until opened. Press "
            "<strong>Esc</strong>, click the backdrop, or use a close "
            "button to dismiss it.</p>")
    footer = ('<button type="button" data-modal-close="sy-demo-modal">Cancel</button>'
              '<button type="button" data-modal-close="sy-demo-modal">Confirm</button>')
    return (
        modal_style()
        + open_button("Open dialog", target="sy-demo-modal")
        + render_modal("sy-demo-modal", "Confirm action", body, footer_html=footer)
        + modal_script()
    )


def _selftest() -> None:
    assert _STYLE_ID in modal_style() and "var(--z-modal)" in modal_style()

    m = render_modal("m1", "Title", "<p>Body</p>")
    assert 'role="dialog"' in m and 'aria-modal="true"' in m
    assert 'aria-labelledby="m1-title"' in m and 'id="m1-title"' in m
    assert " hidden>" in m                       # hidden by default
    assert 'data-modal-close="m1"' in m          # backdrop + close wired
    assert "<p>Body</p>" in m                     # body inserted verbatim

    ob = open_button("Go", target="m1")
    assert 'data-modal-open="m1"' in ob and "Go" in ob

    scr = modal_script()
    assert scr.startswith("<script") and _SCRIPT_ID in scr
    assert "Escape" in scr and "m.hidden" in scr
    assert "eval(" not in scr and "__syModalWired" in scr  # no eval, idempotent

    assert "sy-modal" in demo() and "data-modal-open" in demo()

    # ADVERSARIAL (XSS): the dialog title is escaped even though body is verbatim
    evil = render_modal("m2", "<script>alert(1)</script>", "<p>ok</p>")
    assert '<h2 class="sy-modal-title" id="m2-title"><script>' not in evil
    assert "&lt;script&gt;" in evil

    print("modal selftest OK")


if __name__ == "__main__":
    _selftest()
