"""
google_api_client_wrapper — Wraps Google API interactions (googleapis.com) with real
HTTP execution via requests, bearer-token auth from supplied credentials, typed
responses, clear error handling, and an explicit offline mode for tests.

### PART-META-JSON
{
  "name": "google_api_client_wrapper",
  "layer": "connectors",
  "purpose": "Executes real Google API calls against https://www.googleapis.com using requests with a bearer token taken from the supplied credentials (dict with access_token/token, or raw token string), maps HTTP failures to typed exceptions, and offers get_user_info plus a generic execute_api_call. An explicit offline=True mode serves caller-seeded plain-dict responses so selftests run without network.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "requests"
  ],
  "inputs": "OAuth2 credentials (dict containing access_token/token, or a raw bearer token string), OAuth scopes list, HTTP method/path/body for API calls; offline flag and canned responses for tests.",
  "outputs": "Parsed JSON responses as dicts; get_user_info returns {user_id, email, name, verified}.",
  "files_created": [],
  "security_notes": "Handles live OAuth2 bearer tokens: tokens are sent only in the Authorization header to https://www.googleapis.com over TLS and are never logged (log lines carry scopes/paths, not credentials). Tokens are held in memory on the instance - do not pickle or serialize instances. Error messages include Google's response body excerpt, which for auth failures can echo token metadata; treat raised exception text as sensitive in logs. Offline mode performs zero network I/O and must never be enabled in production paths. This wrapper does not refresh tokens; pair with oauth2_refresh_flow for expiry handling.",
  "ai_usage": "client = GoogleAPIClientWrapper({'access_token': tok}, scopes); client.get_user_info(uid) or client.execute_api_call('GET', '/drive/v3/files'). For tests: GoogleAPIClientWrapper(creds, scopes, offline=True) plus seed_offline_response().",
  "example": "from scrapyard.connectors.google_api_client_wrapper import GoogleAPIClientWrapper",
  "import_path": "scrapyard.connectors.google_api_client_wrapper"
}
### END-PART-META
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.googleapis.com"
DEFAULT_TIMEOUT = 30.0


class GoogleAPIError(Exception):
    """Base exception for Google API failures."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class GoogleAuthError(GoogleAPIError):
    """401/403 from Google (bad, expired, or under-scoped token)."""


class GoogleNotFoundError(GoogleAPIError):
    """404 from Google."""


class GoogleAPIClientWrapper:
    """Wraps Google API interactions with typed responses and error handling.

    Real mode (default) performs HTTPS requests to googleapis.com using the
    bearer token from `credentials`. `offline=True` switches to an explicit
    test mode that serves responses seeded via seed_offline_response() /
    seed_offline_error() and performs no network I/O.
    """

    def __init__(self, credentials: Union[dict, str], scopes: List[str], *,
                 base_url: str = DEFAULT_BASE_URL,
                 timeout: float = DEFAULT_TIMEOUT,
                 offline: bool = False,
                 session: Optional[requests.Session] = None):
        if not credentials:
            raise ValueError("credentials are required (token dict or bearer string)")
        self.credentials = credentials
        self.scopes = list(scopes)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.offline = offline
        self._session = session
        self._offline_responses: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._offline_errors: Dict[Tuple[str, str], Exception] = {}
        logger.info("Initialized GoogleAPIClientWrapper (%d scopes, offline=%s)",
                    len(self.scopes), offline)

    # -- offline test-mode seeding -------------------------------------------------
    def seed_offline_response(self, method: str, path: str,
                              response: Dict[str, Any]) -> None:
        """Register a canned response for (method, path) in offline mode."""
        self._offline_responses[(method.upper(), path)] = response

    def seed_offline_error(self, method: str, path: str, error: Exception) -> None:
        """Register an exception to raise for (method, path) in offline mode."""
        self._offline_errors[(method.upper(), path)] = error

    # -- auth ---------------------------------------------------------------------
    def _token(self) -> str:
        if isinstance(self.credentials, dict):
            token = self.credentials.get("access_token") or self.credentials.get("token") or ""
        else:
            token = self.credentials
        if not token:
            raise GoogleAuthError("no access token present in credentials")
        return token

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
        }

    # -- execution ----------------------------------------------------------------
    def execute_api_call(self, method: str, path: str,
                         body: Optional[Dict] = None,
                         params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a Google API call and return the parsed JSON response.

        In real mode this issues an HTTPS request to `{base_url}{path}` with
        bearer auth; in offline mode it serves seeded responses/errors.
        """
        method = method.upper()
        logger.debug("Executing %s %s", method, path)

        if self.offline:
            key = (method, path)
            if key in self._offline_errors:
                raise self._offline_errors[key]
            if key in self._offline_responses:
                return self._offline_responses[key]
            raise GoogleAPIError(
                f"offline mode: no seeded response for {method} {path}")

        url = self.base_url + (path if path.startswith("/") else "/" + path)
        sess = self._session or requests
        try:
            resp = sess.request(method, url, headers=self._get_headers(),
                                json=body, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise GoogleAPIError(f"network error calling {method} {path}: {exc}") from exc

        if resp.status_code in (401, 403):
            raise GoogleAuthError(
                f"Google auth failure ({resp.status_code}) on {method} {path}: "
                f"{resp.text[:300]}", resp.status_code)
        if resp.status_code == 404:
            raise GoogleNotFoundError(
                f"Google resource not found: {method} {path}", 404)
        if not (200 <= resp.status_code < 300):
            raise GoogleAPIError(
                f"Google API error {resp.status_code} on {method} {path}: "
                f"{resp.text[:300]}", resp.status_code)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Retrieve OAuth2 userinfo for the authorized token.

        Returns {user_id, email, name, verified}.
        """
        raw = self.execute_api_call("GET", "/oauth2/v2/userinfo")
        return {
            "user_id": user_id,
            "email": raw.get("email", ""),
            "name": raw.get("name", ""),
            "verified": raw.get("verified_email", raw.get("email_verified", False)),
        }


def _selftest():
    """Offline-mode selftest: no network I/O."""
    scopes = ["https://www.googleapis.com/auth/userinfo.profile"]

    # Instantiation with dict and string credentials
    client = GoogleAPIClientWrapper({"access_token": "ya29.test_token"}, scopes,
                                    offline=True)
    assert client.scopes == scopes
    client_str = GoogleAPIClientWrapper("raw_access_token", ["s1", "s2"], offline=True)
    assert client_str._token() == "raw_access_token"
    assert client._get_headers()["Authorization"] == "Bearer ya29.test_token"

    # Missing credentials rejected
    try:
        GoogleAPIClientWrapper("", scopes)
        raise AssertionError("empty credentials must raise")
    except ValueError:
        pass

    # Offline userinfo path
    client.seed_offline_response("GET", "/oauth2/v2/userinfo", {
        "email": "alice@example.com", "name": "Alice Smith", "verified_email": True,
    })
    info = client.get_user_info("user_12345")
    assert info == {"user_id": "user_12345", "email": "alice@example.com",
                    "name": "Alice Smith", "verified": True}, info

    # Generic call + error propagation
    client.seed_offline_response("GET", "/test/endpoint", {"id": "123", "status": "active"})
    assert client.execute_api_call("GET", "/test/endpoint")["id"] == "123"

    client.seed_offline_error("POST", "/fail", GoogleAPIError("Connection timeout"))
    try:
        client.execute_api_call("POST", "/fail", {"key": "value"})
        raise AssertionError("seeded error must raise")
    except GoogleAPIError as e:
        assert "Connection timeout" in str(e)

    # Unseeded offline call is an honest error, not a fabricated success
    try:
        client.execute_api_call("DELETE", "/never/seeded")
        raise AssertionError("unseeded offline call must raise")
    except GoogleAPIError as e:
        assert "no seeded response" in str(e)

    # Real path wiring (no network): verify the request that WOULD be sent,
    # using a stub session object with the requests.Session interface.
    captured = {}

    class _StubResp:
        status_code = 200
        content = b'{"ok": true}'
        text = '{"ok": true}'

        @staticmethod
        def json():
            return {"ok": True}

    class _StubSession:
        def request(self, method, url, **kwargs):
            captured.update(method=method, url=url, **kwargs)
            return _StubResp()

    real = GoogleAPIClientWrapper({"access_token": "tok"}, scopes,
                                  session=_StubSession())
    assert real.offline is False
    out = real.execute_api_call("get", "drive/v3/files", params={"q": "x"})
    assert out == {"ok": True}
    assert captured["method"] == "GET"
    assert captured["url"] == "https://www.googleapis.com/drive/v3/files"
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["params"] == {"q": "x"}
    assert captured["timeout"] == DEFAULT_TIMEOUT

    # HTTP error mapping through the real path
    class _Auth401(_StubSession):
        def request(self, method, url, **kwargs):
            r = _StubResp()
            r.status_code = 401
            r.text = "Invalid Credentials"
            return r

    bad = GoogleAPIClientWrapper("expired", scopes, session=_Auth401())
    try:
        bad.execute_api_call("GET", "/oauth2/v2/userinfo")
        raise AssertionError("401 must raise GoogleAuthError")
    except GoogleAuthError as e:
        assert e.status_code == 401

    print("google_api_client_wrapper selftest: all tests passed")
    return True


if __name__ == "__main__":
    _selftest()
