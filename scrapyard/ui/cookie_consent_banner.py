"""
cookie_consent_banner — GDPR consent bar with a localStorage-backed JS helper.

### PART-META-JSON
{
  "name": "cookie_consent_banner",
  "layer": "ui",
  "purpose": "Render a GDPR-style cookie consent bar fixed to the bottom of the viewport, with Accept / Reject / Manage actions. A small inline vanilla-JS helper persists the visitor's choice to localStorage and hides the banner once a choice exists, so it never re-appears on the next visit. Styled from design tokens.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "message text; button labels (accept/reject/manage); storage key; optional policy link href.",
  "outputs": "banner_style()/render_banner(...) -> markup; banner_script(storage_key) -> <script> persisting choice + hiding; demo() -> banner + script.",
  "files_created": [],
  "security_notes": "The message, all button labels, and the policy href are escaped with html.escape, so caller strings cannot inject markup or break out of the href attribute. The script only reads/writes a single localStorage key and toggles the [hidden] attribute — no eval, no innerHTML, no external libraries. It dispatches a 'sy-consent' CustomEvent so a host page can react without this part touching analytics.",
  "ai_usage": "html = render_banner(policy_href='/privacy'); include banner_script() once; listen for window 'sy-consent' events to enable/disable tracking.",
  "example": "from scrapyard.ui.cookie_consent_banner import render_banner; render_banner()",
  "import_path": "scrapyard.ui.cookie_consent_banner"
}
### END-PART-META
"""
from __future__ import annotations

import html

STATUS = "core"

_STYLE_ID = "sy-consent-css"
_SCRIPT_ID = "sy-consent-js"
_BANNER_ID = "sy-consent-banner"
_DEFAULT_KEY = "sy-cookie-consent"

_STYLE = """\
<style id="%s">
#%s[hidden] { display: none; }
#%s {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: var(--z-sticky);
  display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3);
  background: var(--color-surface); color: var(--color-text);
  border-top: 1px solid var(--color-border); box-shadow: var(--shadow-lg);
  padding: var(--space-3) var(--space-4); font-size: var(--text-sm);
  line-height: var(--leading-normal);
}
.sy-consent-text { flex: 1; min-width: 240px; }
.sy-consent-text a { color: var(--color-primary); }
.sy-consent-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.sy-consent-btn {
  font: inherit; font-weight: var(--weight-medium); cursor: pointer;
  border-radius: var(--radius-sm); padding: var(--space-2) var(--space-4); border: 0;
}
.sy-consent-accept { background: var(--color-primary); color: #fff; }
.sy-consent-reject, .sy-consent-manage {
  background: transparent; color: var(--color-text);
  border: 1px solid var(--color-border);
}
</style>
""" % (_STYLE_ID, _BANNER_ID, _BANNER_ID)


def banner_style() -> str:
    """The <style> block for the consent bar (id-guarded; include once)."""
    return _STYLE


def render_banner(
    *,
    message: str = "We use cookies to run this site and, with your consent, to measure traffic.",
    accept_label: str = "Accept",
    reject_label: str = "Reject",
    manage_label: str = "Manage",
    policy_href: str | None = None,
    policy_label: str = "Learn more",
) -> str:
    """The fixed-bottom consent bar. All text and the policy href are escaped.
    Buttons carry data-consent="accept|reject|manage" for the script to wire."""
    text = html.escape(message)
    if policy_href is not None:
        text += (f' <a href="{html.escape(policy_href)}">'
                 f"{html.escape(policy_label)}</a>")
    return (
        f'<div id="{_BANNER_ID}" class="sy-consent-banner" role="dialog" '
        f'aria-label="Cookie consent" aria-live="polite">'
        f'<div class="sy-consent-text">{text}</div>'
        f'<div class="sy-consent-actions">'
        f'<button type="button" class="sy-consent-btn sy-consent-manage" '
        f'data-consent="manage">{html.escape(manage_label)}</button>'
        f'<button type="button" class="sy-consent-btn sy-consent-reject" '
        f'data-consent="reject">{html.escape(reject_label)}</button>'
        f'<button type="button" class="sy-consent-btn sy-consent-accept" '
        f'data-consent="accept">{html.escape(accept_label)}</button>'
        f"</div></div>"
    )


def banner_script(*, storage_key: str = _DEFAULT_KEY) -> str:
    """A <script> that persists the choice to localStorage and hides the banner.
    Idempotent (guarded flag). On load, if a prior choice exists the banner is
    hidden immediately. 'manage' does not hide (it opens host preferences via a
    dispatched event). No eval, no external libraries."""
    key = html.escape(storage_key)
    return f"""\
<script id="{_SCRIPT_ID}">
(function () {{
  if (window.__syConsentWired) return;
  window.__syConsentWired = true;
  var KEY = {key!r};
  function store() {{ try {{ return window.localStorage; }} catch (e) {{ return null; }} }}
  function banner() {{ return document.getElementById({_BANNER_ID!r}); }}
  function emit(choice) {{
    window.dispatchEvent(new CustomEvent('sy-consent', {{ detail: {{ choice: choice }} }}));
  }}
  function apply() {{
    var s = store(); var b = banner();
    if (!b) return;
    var prior = s ? s.getItem(KEY) : null;
    if (prior === 'accept' || prior === 'reject') b.hidden = true;
  }}
  document.addEventListener('click', function (e) {{
    var btn = e.target.closest('[data-consent]');
    if (!btn) return;
    var choice = btn.getAttribute('data-consent');
    if (choice === 'manage') {{ emit('manage'); return; }}
    var s = store();
    if (s) {{ try {{ s.setItem(KEY, choice); }} catch (e2) {{}} }}
    var b = banner(); if (b) b.hidden = true;
    emit(choice);
  }});
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', apply);
  }} else {{ apply(); }}
}})();
</script>"""


def demo() -> str:
    """The consent bar plus its persistence script — self-contained."""
    return (
        banner_style()
        + render_banner(policy_href="#privacy")
        + banner_script()
    )


def _selftest() -> None:
    assert _STYLE_ID in banner_style() and "var(--z-sticky)" in banner_style()

    b = render_banner(policy_href="/privacy")
    assert _BANNER_ID in b and 'role="dialog"' in b
    for choice in ("accept", "reject", "manage"):
        assert f'data-consent="{choice}"' in b
    assert 'href="/privacy"' in b

    scr = banner_script()
    assert scr.startswith("<script") and _SCRIPT_ID in scr
    assert "localStorage" in scr and "setItem" in scr and "b.hidden = true" in scr
    assert "eval(" not in scr and "__syConsentWired" in scr  # no eval, idempotent
    # a custom storage key flows into the script literal
    assert "'my-key'" in banner_script(storage_key="my-key")

    assert "sy-consent" in demo() and "localStorage" in demo()

    # ADVERSARIAL (XSS): message + policy href are escaped, not raw
    evil = render_banner(message="<script>alert(1)</script>",
                         policy_href='"><script>bad()</script>')
    assert "<script>alert(1)</script>" not in evil
    assert "&lt;script&gt;" in evil
    assert '"><script>bad()' not in evil  # href quote is entity-escaped

    print("cookie_consent_banner selftest OK")


if __name__ == "__main__":
    _selftest()
