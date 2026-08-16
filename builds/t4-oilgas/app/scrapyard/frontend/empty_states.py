"""
empty_states — Reusable empty/error/loading states.

### PART-META-JSON
{
  "name": "empty_states",
  "layer": "frontend",
  "purpose": "Python server-side HTML rendering of reusable empty/error/loading state blocks (stdlib html escaping, no react).",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: render_empty_state(title, message, *, action_label, action_href); render_error_state(title, message, *, action_label, action_href, error_code); render_loading_state(title, message, *, spinner_class); render_list_empty_state(title, message, *, action_label, action_href, list_name); render_with_fallback(content, fallback_title, fallback_message, *, fallback_action_label, fallback_action_href) (plus more).",
  "outputs": "Returns: render_error_state -> str; render_loading_state -> str; render_list_empty_state -> str; render_with_fallback -> str; render_with_error_fallback -> str.",
  "files_created": [],
  "security_notes": "Messages and titles are escaped with html.escape (XSS-safe). Error states should show user-safe text only - never raw exception detail from the server.",
  "ai_usage": "Import `render_empty_state` from `scrapyard.frontend.empty_states` and call it as shown in `example`; run `py -m scrapyard.frontend.empty_states` to see its offline selftest.",
  "example": "from scrapyard.frontend.empty_states import render_empty_state",
  "import_path": "scrapyard.frontend.empty_states"
}
### END-PART-META
"""
from __future__ import annotations
import html
STATUS = "core"

def render_empty_state(title, message, *, action_label=None, action_href=None):
    e = html.escape
    cta = f'<a class="cta" href="{e(action_href)}">{e(action_label)}</a>' if action_label and action_href else ""
    return f'<div class="empty-state"><h3>{e(title)}</h3><p>{e(message)}</p>{cta}</div>'

def render_error_state(title: str, message: str, *, action_label: None = None, action_href: None = None, error_code: None = None) -> str:
    e = html.escape
    cta = f'<a class="cta" href="{e(action_href)}">{e(action_label)}</a>' if action_label and action_href else ""
    return (
        f'<div class="error-state">'
        f'<h3>{e(title)}</h3>'
        f'<p>{e(message)}</p>'
        f'{cta}'
        f'</div>'
    )

def render_loading_state(title: str, message: str, *, spinner_class: str = "default-spinner") -> str:
    e = html.escape
    return (
        f'<div class="loading-state">'
        f'<h3>{e(title)}</h3>'
        f'<p>{e(message)}</p>'
        f'<span class="{e(spinner_class)}"></span>'
        '</div>'
    )

def render_list_empty_state(title: str, message: str, *, action_label: None = None, action_href: None = None, list_name: str = "items") -> str:
    e = html.escape
    cta = f'<a class="cta" href="{e(action_href)}">{e(action_label)}</a>' if action_label and action_href else ""
    return (
        f'<div class="list-empty-state">'
        f'<h3>{e(title)}</h3>'
        f'<p>No {e(list_name)} found.</p>'
        f'{cta}'
        '</div>'
    )

def render_with_fallback(content: None, fallback_title: str, fallback_message: str, *, fallback_action_label: None = None, fallback_action_href: None = None) -> str:
    if content is not None:
        return content
    else:
        e = html.escape
        cta = f'<a class="cta" href="{e(fallback_action_href)}">{e(fallback_action_label)}</a>' if fallback_action_label and fallback_action_href else ""
        return (
            f'<div class="fallback-state">'
            f'<h3>{e(fallback_title)}</h3>'
            f'<p>{e(fallback_message)}</p>'
            f'{cta}'
            '</div>'
        )

def render_with_error_fallback(content: None, error_title: str, error_message: str, *, error_action_label: None = None, error_action_href: None = None) -> str:
    if content is not None:
        return content
    else:
        e = html.escape
        cta = f'<a class="cta" href="{e(error_action_href)}">{e(error_action_label)}</a>' if error_action_label and error_action_href else ""
        return (
            f'<div class="error-fallback-state">'
            f'<h3>{e(error_title)}</h3>'
            f'<p>{e(error_message)}</p>'
            f'{cta}'
            '</div>'
        )

def render_with_loading_fallback(content: None, loading_title: str, loading_message: str, *, spinner_class: str = "default-spinner") -> str:
    if content is not None:
        return content
    else:
        e = html.escape
        return (
            f'<div class="loading-fallback-state">'
            f'<h3>{e(loading_title)}</h3>'
            f'<p>{e(loading_message)}</p>'
            f'<span class="{e(spinner_class)}"></span>'
            '</div>'
        )

def render_custom_state(title: str, message: str, *, custom_html: None = None, **kwargs) -> str:
    e = html.escape
    if custom_html is not None:
        return (
            f'<div class="custom-state">'
            f'{e(custom_html)}'
            '</div>'
        )
    else:
        cta = kwargs.get('cta', "")
        return (
            f'<div class="custom-state">'
            f'<h3>{e(title)}</h3>'
            f'<p>{e(message)}</p>'
            f'{cta}'
            '</div>'
        )


def _selftest() -> None:
    # empty state with CTA
    es = render_empty_state("No items", "Get started", action_label="Add", action_href="/add")
    assert 'class="empty-state"' in es and "<h3>No items</h3>" in es and "Get started" in es
    assert 'href="/add"' in es and ">Add<" in es
    # CTA omitted when href missing
    assert 'class="cta"' not in render_empty_state("t", "m")
    # error + list-empty states
    err = render_error_state("Oops", "Something failed")
    assert 'class="error-state"' in err and "<h3>Oops</h3>" in err
    le = render_list_empty_state("Empty", "", list_name="orders")
    assert "No orders found." in le
    # fallback returns real content when present, fallback block when None
    assert render_with_fallback("<p>real</p>", "t", "m") == "<p>real</p>"
    assert "fallback-state" in render_with_fallback(None, "T", "M")
    # ADVERSARIAL: XSS neutralized across empty / error / loading states
    xss = "<script>alert(1)</script>"
    assert "<script>" not in render_empty_state(xss, xss)
    assert "&lt;script&gt;" in render_empty_state(xss, "m")
    assert "<script>" not in render_error_state(xss, xss)
    assert "<script>" not in render_loading_state(xss, xss)
    print("empty_states selftest OK")


if __name__ == "__main__":
    _selftest()
