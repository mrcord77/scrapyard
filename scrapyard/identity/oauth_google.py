"""
oauth_google — Google OAuth2 sign-in (authorize + callback).

### PART-META-JSON
{
  "name": "oauth_google",
  "layer": "identity",
  "purpose": "Google OAuth2 sign-in (authorize + callback).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "authlib"
  ],
  "inputs": "Public API: authorize_url(*, redirect_uri, state, client_id); exchange_code(code, *, redirect_uri).",
  "outputs": "Returns: authorize_url -> str; exchange_code -> dict.",
  "files_created": [],
  "security_notes": "Makes outbound network calls; set timeouts, validate URLs/hosts, and never send secrets to untrusted endpoints.",
  "ai_usage": "Import `authorize_url` from `scrapyard.identity.oauth_google` and call it as shown in `example`; run `py -m scrapyard.identity.oauth_google` to see its offline selftest.",
  "example": "from scrapyard.identity.oauth_google import authorize_url",
  "import_path": "scrapyard.identity.oauth_google"
}
### END-PART-META
"""
from __future__ import annotations
import os
STATUS = "core"
def authorize_url(*, redirect_uri: str, state: str, client_id: str | None=None) -> str:
    """Build the Google OAuth consent URL. Token exchange uses the real endpoint
    when GOOGLE_CLIENT_SECRET is set (see exchange_code)."""
    from urllib.parse import urlencode
    cid=client_id or os.environ.get("GOOGLE_CLIENT_ID","")
    q=urlencode({"client_id":cid,"redirect_uri":redirect_uri,"response_type":"code",
                 "scope":"openid email profile","state":state})
    return "https://accounts.google.com/o/oauth2/v2/auth?"+q
def exchange_code(code: str, *, redirect_uri: str) -> dict:
    import urllib.request, urllib.parse, json
    cid=os.environ.get("GOOGLE_CLIENT_ID"); sec=os.environ.get("GOOGLE_CLIENT_SECRET")
    if not (cid and sec):
        raise RuntimeError("GOOGLE_CLIENT_ID/SECRET not configured")
    data=urllib.parse.urlencode({"code":code,"client_id":cid,"client_secret":sec,
        "redirect_uri":redirect_uri,"grant_type":"authorization_code"}).encode()
    req=urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req) as r: return json.loads(r.read())


def _selftest() -> None:
    """Offline self-test: consent-URL construction + configuration guard.

    The live token exchange requires Google's endpoint + real credentials, so
    only the verifiable sub-logic is tested; the network round-trip is not faked.
    """
    from urllib.parse import urlparse, parse_qs

    # authorize_url embeds every OAuth param and the anti-CSRF state.
    url = authorize_url(redirect_uri="https://app.example.com/cb",
                        state="xyz-state-123", client_id="cid-abc")
    parsed = urlparse(url)
    assert parsed.netloc == "accounts.google.com", "must target Google's consent host"
    q = parse_qs(parsed.query)
    assert q["state"] == ["xyz-state-123"], "state (CSRF token) must be carried through"
    assert q["client_id"] == ["cid-abc"]
    assert q["redirect_uri"] == ["https://app.example.com/cb"]
    assert q["response_type"] == ["code"], "authorization-code flow"

    # negative: two distinct states produce distinct URLs (state is not dropped).
    other = authorize_url(redirect_uri="https://app.example.com/cb",
                          state="different-state", client_id="cid-abc")
    assert other != url, "distinct state must yield a distinct consent URL"

    # negative/adversarial: exchanging a code with no configured secret is refused
    # (never silently proceeds), rather than hitting the network.
    old_id = os.environ.pop("GOOGLE_CLIENT_ID", None)
    old_secret = os.environ.pop("GOOGLE_CLIENT_SECRET", None)
    try:
        try:
            exchange_code("any-code", redirect_uri="https://app.example.com/cb")
            raise AssertionError("unconfigured exchange_code must raise RuntimeError")
        except RuntimeError:
            pass
    finally:
        if old_id is not None:
            os.environ["GOOGLE_CLIENT_ID"] = old_id
        if old_secret is not None:
            os.environ["GOOGLE_CLIENT_SECRET"] = old_secret
    print("oauth_google self-test passed")


if __name__ == "__main__":
    _selftest()
