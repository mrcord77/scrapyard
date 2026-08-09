"""
csrf — Double-submit CSRF protection for cookie auth.

### PART-META-JSON
{
  "name": "csrf",
  "layer": "security",
  "purpose": "Double-submit CSRF protection for cookie auth.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: issue_token(secret, session_id); validate_token(token, secret, session_id); get_csrf_cookie(token, name, max_age); get_csrf_header(token, name); get_csrf_middleware(secret, session_id_extractor); ValidationResult(...); CSRFError(...) (plus more).",
  "outputs": "Returns: issue_token -> str; validate_token -> bool; get_csrf_cookie -> dict; get_csrf_header -> dict; get_csrf_middleware -> callable.",
  "files_created": [],
  "security_notes": "Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `issue_token` from `scrapyard.security.csrf` and call it as shown in `example`; run `py -m scrapyard.security.csrf` to see its offline selftest.",
  "example": "from scrapyard.security.csrf import issue_token",
  "import_path": "scrapyard.security.csrf"
}
### END-PART-META
"""
from __future__ import annotations
import hmac, hashlib, secrets
from typing import Optional, Callable

STATUS = "core"

def issue_token(secret: str, session_id: str) -> str:
    nonce = secrets.token_urlsafe(16)
    sig = hmac.new(secret.encode(), f"{session_id}:{nonce}".encode(), hashlib.sha256).hexdigest()
    return f"{nonce}.{sig}"

def validate_token(token: str, secret: str, session_id: str) -> bool:
    try:
        nonce, sig = token.split(".", 1)
        expected = hmac.new(secret.encode(), f"{session_id}:{nonce}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False

class ValidationResult:
    def __init__(self, status: str, message: Optional[str] = None):
        self.status = status
        self.message = message

class CSRFError(Exception):
    def __init__(self, detail: str, status_code: int = 403):
        self.detail = detail
        self.status_code = status_code

def get_csrf_cookie(token: str, name: str = "csrf_token", max_age: int = 3600) -> dict:
    return {
        "key": name,
        "value": token,
        "httponly": True,
        "samesite": "Lax",
        "secure": True,
        "max_age": max_age
    }

def get_csrf_header(token: str, name: str = "X-CSRF-Token") -> dict:
    return {"key": name, "value": token}

def get_csrf_middleware(secret: str, session_id_extractor: Callable[[object], str]) -> callable:
    def middleware(request):
        session_id = session_id_extractor(request)
        if not validate_csrf_request(request, session_id, secret).status == "Valid":
            raise CSRFError("CSRF validation failed")
    return middleware

def configure_csrf_defaults(nonce_length: int = 16, cookie_name: str = "csrf_token", header_name: str = "X-CSRF-Token"):
    global NONCE_LENGTH, COOKIE_NAME, HEADER_NAME
    NONCE_LENGTH = nonce_length
    COOKIE_NAME = cookie_name
    HEADER_NAME = header_name

def set_csrf_secret(secret: str):
    global CSRF_SECRET
    CSRF_SECRET = secret

def get_csrf_secret() -> str:
    return CSRF_SECRET

def validate_csrf_request(request, session_id, secret: Optional[str] = None) -> ValidationResult:
    # Use the secret supplied by the caller/middleware; fall back to the global
    # only when none is provided. A middleware built with an explicit secret must
    # validate tokens signed with THAT secret, not the global CSRF_SECRET.
    secret = secret if secret is not None else CSRF_SECRET
    cookie_token = request.cookies.get(COOKIE_NAME)
    header_token = request.headers.get(HEADER_NAME)

    if not (cookie_token and header_token):
        return ValidationResult(status="Invalid", message="Missing token")

    if validate_token(cookie_token, secret, session_id) and \
       validate_token(header_token, secret, session_id):
        return ValidationResult(status="Valid")
    else:
        return ValidationResult(status="Invalid")

def generate_and_set_csrf_cookie(response, session_id) -> object:
    token = issue_token(CSRF_SECRET, session_id)
    response.set_cookie(**get_csrf_cookie(token))
    return response

def generate_and_set_csrf_header(response, session_id) -> object:
    token = issue_token(CSRF_SECRET, session_id)
    response.headers[HEADER_NAME] = token
    return response

def generate_and_set_csrf(response, session_id) -> object:
    response = generate_and_set_csrf_cookie(response, session_id)
    response = generate_and_set_csrf_header(response, session_id)
    return response

def csrf_error_response(message: str, status_code: int = 403) -> dict:
    return {"detail": message}, status_code

def csrf_middleware_factory(secret: str, session_id_extractor: Callable[[object], str]) -> callable:
    def middleware(request):
        session_id = session_id_extractor(request)
        if not validate_csrf_request(request, session_id, secret).status == "Valid":
            raise CSRFError("CSRF validation failed")
    return middleware

def _selftest() -> None:
    """Offline, falsifiable self-test of the double-submit CSRF logic."""
    secret, sess = "s3cr3t-key", "user-42"

    # 1) a freshly issued token validates against its (secret, session)
    tok = issue_token(secret, sess)
    assert validate_token(tok, secret, sess) is True, "issued token must validate"

    # 2) NEGATIVE: a forged/tampered signature is rejected
    nonce, sig = tok.split(".", 1)
    forged = f"{nonce}.{'0' * len(sig)}"
    assert validate_token(forged, secret, sess) is False, "forged signature must fail"

    # 3) NEGATIVE: same token, WRONG session must not validate (binding holds)
    assert validate_token(tok, secret, "someone-else") is False, "session binding must hold"
    # ...and a wrong secret must not validate
    assert validate_token(tok, "wrong-secret", sess) is False, "secret binding must hold"

    # 4) end-to-end request validation via the double-submit check
    set_csrf_secret(secret)
    configure_csrf_defaults()

    class _Req:
        def __init__(self, cookie, header):
            self.cookies = {COOKIE_NAME: cookie} if cookie is not None else {}
            self.headers = {HEADER_NAME: header} if header is not None else {}

    good = issue_token(secret, sess)
    assert validate_csrf_request(_Req(good, good), sess).status == "Valid", \
        "matching cookie+header must be Valid"
    # NEGATIVE: missing header token is rejected
    assert validate_csrf_request(_Req(good, None), sess).status == "Invalid", \
        "missing header token must be Invalid"
    # NEGATIVE: a forged header token is rejected even with a valid cookie
    assert validate_csrf_request(_Req(good, forged), sess).status == "Invalid", \
        "forged header token must be Invalid"

    # EXPLOIT REGRESSION: the middleware factory must USE its `secret` argument,
    # not the global CSRF_SECRET. Point the global at a DIFFERENT secret so a
    # factory that ignored its own arg would reject its own tokens.
    set_csrf_secret("global-secret-not-the-factory-one")
    factory_secret = "factory-provided-secret"
    extractor = lambda req: req.session_id

    class _MwReq:
        def __init__(self, cookie, header, sid):
            self.session_id = sid
            self.cookies = {COOKIE_NAME: cookie} if cookie is not None else {}
            self.headers = {HEADER_NAME: header} if header is not None else {}

    factory_tok = issue_token(factory_secret, sess)  # signed with the factory secret
    for factory in (csrf_middleware_factory, get_csrf_middleware):
        mw = factory(factory_secret, extractor)
        # a token signed with the SAME secret the middleware was built with passes
        mw(_MwReq(factory_tok, factory_tok, sess))  # must not raise
        # a token signed with a DIFFERENT secret is rejected
        wrong_tok = issue_token("some-other-secret", sess)
        try:
            mw(_MwReq(wrong_tok, wrong_tok, sess))
            raise AssertionError(f"{factory.__name__}: wrong-secret token must be rejected")
        except CSRFError:
            pass
    set_csrf_secret(secret)

    print("csrf: OK (9 assertions incl. forged/missing-token + secret-honored negatives)")


if __name__ == "__main__":
    _selftest()
