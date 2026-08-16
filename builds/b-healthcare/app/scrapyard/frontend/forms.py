"""
forms — Accessible form fields + validation display.

### PART-META-JSON
{
  "name": "forms",
  "layer": "frontend",
  "purpose": "Python server-side HTML rendering of accessible form fields with validation error display (stdlib html escaping, no react).",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: render_field(name, *, label, type, value, required, error); render_form(action, fields, *, method, submit, csrf_token).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Field names/labels/values and error strings are escaped with html.escape (XSS-safe). Pair with CSRF tokens at the endpoint; never prefill password fields.",
  "ai_usage": "Import `render_field` from `scrapyard.frontend.forms` and call it as shown in `example`; run `py -m scrapyard.frontend.forms` to see its offline selftest.",
  "example": "from scrapyard.frontend.forms import render_field",
  "import_path": "scrapyard.frontend.forms"
}
### END-PART-META
"""
from __future__ import annotations
import html
STATUS = "core"
def render_field(name, *, label=None, type="text", value="", required=False, error=None):
    e=html.escape; req=" required" if required else ""
    err=f'<span class="error">{e(error)}</span>' if error else ""
    return (f'<label for="{e(name)}">{e(label or name)}</label>'
            f'<input id="{e(name)}" name="{e(name)}" type="{e(type)}" value="{e(str(value))}"{req}>{err}')
def render_form(action, fields, *, method="post", submit="Submit", csrf_token=None):
    parts=[f'<form action="{html.escape(action)}" method="{html.escape(method)}">']
    if csrf_token: parts.append(f'<input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">')
    parts.extend(render_field(**f) for f in fields)
    parts.append(f'<button type="submit">{html.escape(submit)}</button></form>')
    return "\n".join(parts)


def _selftest() -> None:
    # render_field: structure + attributes
    f = render_field("email", label="Email", type="email", required=True)
    assert "<input" in f and 'name="email"' in f and 'type="email"' in f
    assert " required" in f
    assert '<label for="email">Email</label>' in f
    # render_form: form wrapper, csrf hidden field, each field's input, submit
    form = render_form("/login", [{"name": "email"}, {"name": "pw", "type": "password"}],
                       csrf_token="tok123")
    assert form.startswith("<form") and "</form>" in form
    assert 'input type="hidden" name="csrf_token" value="tok123"' in form
    assert 'name="email"' in form and 'name="pw"' in form and 'type="password"' in form
    assert '<button type="submit">Submit</button>' in form
    # csrf field absent when no token supplied
    assert "csrf_token" not in render_form("/x", [])
    # ADVERSARIAL: XSS payload must be html-escaped, never emitted raw
    xss = "<script>alert(1)</script>"
    out = render_field("email", value=xss, error=xss)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    form2 = render_form('"><script>', [], submit="<b>go</b>")
    assert "<script>" not in form2 and "&lt;script&gt;" in form2
    print("forms selftest OK")


if __name__ == "__main__":
    _selftest()
