"""
auth_pages — Login/signup/reset UI blocks.

### PART-META-JSON
{
  "name": "auth_pages",
  "layer": "frontend",
  "purpose": "Python server-side HTML rendering of login/signup/password-reset blocks (stdlib html escaping, no react).",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: login_page(*, action, csrf_token, error); register_page(*, action, csrf_token).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "All user-visible strings are escaped with html.escape (XSS-safe). Forms must POST to endpoints that add CSRF protection; never render or log passwords/tokens into the HTML.",
  "ai_usage": "Import `login_page` from `scrapyard.frontend.auth_pages` and call it as shown in `example`; run `py -m scrapyard.frontend.auth_pages` to see its offline selftest.",
  "example": "from scrapyard.frontend.auth_pages import login_page",
  "import_path": "scrapyard.frontend.auth_pages"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
def login_page(*, action="/auth/login", csrf_token=None, error=None):
    from scrapyard.frontend.forms import render_form
    fields=[{"name":"email","label":"Email","type":"email","required":True,"error":error},
            {"name":"password","label":"Password","type":"password","required":True}]
    return "<h1>Sign in</h1>"+render_form(action, fields, submit="Sign in", csrf_token=csrf_token)
def register_page(*, action="/auth/register", csrf_token=None):
    from scrapyard.frontend.forms import render_form
    fields=[{"name":"email","label":"Email","type":"email","required":True},
            {"name":"password","label":"Password","type":"password","required":True}]
    return "<h1>Create account</h1>"+render_form(action, fields, submit="Sign up", csrf_token=csrf_token)


def _selftest() -> None:
    lp = login_page(csrf_token="tok")
    assert "<h1>Sign in</h1>" in lp
    assert "<form" in lp and 'name="email"' in lp and 'name="password"' in lp
    assert 'type="password"' in lp
    assert 'name="csrf_token"' in lp and 'value="tok"' in lp
    assert 'action="/auth/login"' in lp
    rp = register_page(action="/signup")
    assert "<h1>Create account</h1>" in rp and 'action="/signup"' in rp
    assert 'name="email"' in rp and 'name="password"' in rp
    # csrf hidden field absent when no token supplied
    assert "csrf_token" not in register_page()
    # ADVERSARIAL: a user-controlled error string must be escaped, not raw
    xss = "<script>alert(1)</script>"
    lpe = login_page(error=xss)
    assert "<script>" not in lpe
    assert "&lt;script&gt;" in lpe
    print("auth_pages selftest OK")


if __name__ == "__main__":
    _selftest()
