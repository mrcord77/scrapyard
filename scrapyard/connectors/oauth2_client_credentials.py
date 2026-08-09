"""
oauth2_client_credentials — Real OAuth2 client-credentials flow (RFC 6749 §4.4) with a
live token-endpoint POST via requests, cached typed tokens, webhook HMAC verification,
thin real-API wrappers (Stripe/GitHub/Slack), and an explicit offline mode for tests.

### PART-META-JSON
{
  "name": "oauth2_client_credentials",
  "layer": "connectors",
  "purpose": "Obtains and caches OAuth2 access tokens by POSTing grant_type=client_credentials to a real token endpoint (HTTP basic client auth, form-encoded, via requests) with expiry-buffered refresh; verifies webhook HMAC-SHA256 signatures; and provides thin typed wrappers that spend the token against real Stripe/GitHub/Slack endpoints. An explicit offline=True mode mints deterministic, clearly-fake tokens (derived from client_id + counter only, never the secret) so selftests run with zero network I/O.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "requests"
  ],
  "inputs": "client_id, client_secret, token_url (+ optional scope, audience); webhook payload bytes + signature + secret; API call parameters for the bundled wrappers.",
  "outputs": "Bearer access tokens (TokenData with expiry), boolean webhook verdicts, parsed JSON dicts from wrapped APIs.",
  "files_created": [],
  "security_notes": "Handles a live OAuth2 client_secret: it is sent only via HTTP basic auth over TLS to the configured token_url and is never logged, never embedded in token values or cache keys (offline tokens derive from client_id and a counter only). token_url is caller-controlled - pointing it at an attacker's host leaks the client credentials, so treat it as configuration, not user input. Access tokens are cached in process memory; do not serialize instances. Webhook verification uses hmac.compare_digest (constant-time); signatures accept an optional 'sha256=' prefix. Offline mode mints tokens prefixed 'offline_token_' that no real API will accept, and must never be enabled outside tests.",
  "ai_usage": "OAuth2ClientCredentials(cid, secret, token_url).get_access_token() for real tokens; offline=True in tests. verify_webhook_signature(payload, sig, secret) for webhooks.",
  "example": "from scrapyard.connectors.oauth2_client_credentials import OAuth2ClientCredentials",
  "import_path": "scrapyard.connectors.oauth2_client_credentials"
}
### END-PART-META
"""

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


class OAuth2Error(Exception):
    """Base exception for OAuth2 errors."""


class TokenRefreshError(OAuth2Error):
    """Raised when token acquisition/refresh fails."""


@dataclass
class TokenData:
    access_token: str
    expires_at: float
    token_type: str = "Bearer"

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """Check if token is expired or about to expire."""
        return time.time() >= (self.expires_at - buffer_seconds)


class OAuth2ClientCredentials:
    """OAuth2 client-credentials flow (RFC 6749 section 4.4).

    Real mode POSTs grant_type=client_credentials to token_url with HTTP basic
    client authentication and caches the returned bearer token until near
    expiry. offline=True (tests only) mints deterministic fake tokens locally;
    the client_secret never contributes to token material.
    """

    def __init__(self, client_id: str, client_secret: str, token_url: str, *,
                 scope: Optional[str] = None, audience: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT, offline: bool = False,
                 session: Optional[requests.Session] = None):
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required")
        if not token_url:
            raise ValueError("token_url is required")

        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.scope = scope
        self.audience = audience
        self.timeout = timeout
        self.offline = offline
        self._session = session
        self._token_data: Optional[TokenData] = None
        self._offline_token_counter = 0

    # -- offline mode (tests only) ------------------------------------------------
    def _generate_offline_token(self) -> TokenData:
        """Deterministic fake token for the explicit offline mode.

        Derived from client_id + counter only - the client_secret is never
        part of token material - and prefixed so it cannot pass as real.
        """
        self._offline_token_counter += 1
        seed = f"{self.client_id}:{self._offline_token_counter}"
        digest = hashlib.sha256(seed.encode()).hexdigest()[:32]
        return TokenData(access_token=f"offline_token_{digest}",
                         expires_at=time.time() + 3600)

    # -- real token endpoint ------------------------------------------------------
    def _fetch_token(self) -> TokenData:
        """POST the client-credentials grant to the real token endpoint."""
        form: Dict[str, str] = {"grant_type": "client_credentials"}
        if self.scope:
            form["scope"] = self.scope
        if self.audience:
            form["audience"] = self.audience
        sess = self._session or requests
        try:
            resp = sess.post(self.token_url, data=form,
                             auth=(self.client_id, self.client_secret),
                             timeout=self.timeout)
        except requests.RequestException as exc:
            raise TokenRefreshError(
                f"network error reaching token endpoint: {exc}") from exc
        if resp.status_code != 200:
            raise TokenRefreshError(
                f"token endpoint returned {resp.status_code}: {resp.text[:300]}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise TokenRefreshError("token endpoint returned non-JSON body") from exc
        access_token = body.get("access_token")
        if not access_token:
            raise TokenRefreshError(
                f"token response missing access_token: {body.get('error', 'unknown')}")
        expires_in = float(body.get("expires_in", 3600))
        return TokenData(access_token=access_token,
                         expires_at=time.time() + expires_in,
                         token_type=body.get("token_type", "Bearer"))

    # -- public API ---------------------------------------------------------------
    def get_access_token(self) -> str:
        """Get the current access token, refreshing if missing/near expiry."""
        if self._token_data is None or self._token_data.is_expired():
            self.refresh_token()
        if self._token_data is None:
            raise TokenRefreshError("Failed to obtain access token")
        return self._token_data.access_token

    def refresh_token(self) -> str:
        """Force-refresh the access token; returns the new token."""
        if self.offline:
            self._token_data = self._generate_offline_token()
        else:
            self._token_data = self._fetch_token()
        logger.debug("Token refreshed, expires at %s", self._token_data.expires_at)
        return self._token_data.access_token

    def auth_header(self) -> Dict[str, str]:
        """Authorization header dict for the current token."""
        return {"Authorization": f"Bearer {self.get_access_token()}"}


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify a webhook HMAC-SHA256 signature (hex, optional 'sha256=' prefix).

    Raises TypeError for non-bytes payload and ValueError for empty secret;
    returns False (never raises) for malformed signatures.
    """
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if not secret:
        raise ValueError("secret is required")

    if "=" in signature:
        _, _, signature = signature.partition("=")

    try:
        expected_signature = hmac.new(secret.encode("utf-8"), payload,
                                      hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected_signature)
    except Exception as e:
        logger.warning("Signature verification failed: %s", e)
        return False


class WebhookReceiver:
    """Stateful webhook receiver that holds a secret."""

    def __init__(self, secret: str):
        if not secret:
            raise ValueError("secret is required")
        self.secret = secret

    def verify(self, payload: bytes, signature: str) -> bool:
        """Verify a webhook signature against the stored secret."""
        return verify_webhook_signature(payload, signature, self.secret)


class _BearerAPIWrapper:
    """Shared plumbing: real requests with the OAuth token, or deterministic
    plain-dict samples when the oauth client is in explicit offline mode."""

    def __init__(self, oauth_client: OAuth2ClientCredentials,
                 timeout: float = DEFAULT_TIMEOUT):
        self.oauth = oauth_client
        self.timeout = timeout

    def _request(self, method: str, url: str, *, json_body: Optional[Dict] = None,
                 form: Optional[Dict] = None,
                 extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        headers = self.oauth.auth_header()
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = requests.request(method, url, headers=headers, json=json_body,
                                    data=form, timeout=self.timeout)
        except requests.RequestException as exc:
            raise OAuth2Error(f"network error on {method} {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise OAuth2Error(
                f"API error {resp.status_code} on {method} {url}: {resp.text[:300]}")
        return resp.json() if resp.content else {}


class StripeClientWrapper(_BearerAPIWrapper):
    """Thin Stripe wrapper spending the OAuth token against api.stripe.com.

    For full typed Stripe support use scrapyard.connectors.stripe_client_wrapper.
    """

    BASE_URL = "https://api.stripe.com/v1"

    def create_charge(self, amount: int, currency: str, customer_id: str) -> dict:
        """Create a charge; deterministic sample in offline mode."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        if not currency or len(currency) != 3:
            raise ValueError("currency must be 3-letter ISO code")
        if not customer_id:
            raise ValueError("customer_id is required")

        if self.oauth.offline:
            self.oauth.get_access_token()  # exercise the token path
            seed = hashlib.sha256(
                f"{amount}:{currency}:{customer_id}".encode()).hexdigest()
            return {"id": f"ch_offline_{seed[:16]}", "amount": amount,
                    "currency": currency.lower(), "customer": customer_id,
                    "status": "succeeded", "object": "charge",
                    "created": int(time.time())}

        return self._request("POST", f"{self.BASE_URL}/charges", form={
            "amount": amount, "currency": currency.lower(), "customer": customer_id})


class GitHubClientWrapper(_BearerAPIWrapper):
    """Thin GitHub wrapper spending the OAuth token against api.github.com.

    For full typed GitHub support use scrapyard.connectors.github_client_wrapper.
    """

    BASE_URL = "https://api.github.com"

    def get_repo_info(self, repo_owner: str, repo_name: str) -> dict:
        """Fetch repository info; deterministic sample in offline mode."""
        if not repo_owner:
            raise ValueError("repo_owner is required")
        if not repo_name:
            raise ValueError("repo_name is required")

        if self.oauth.offline:
            self.oauth.get_access_token()
            hash_val = hashlib.sha256(f"{repo_owner}/{repo_name}".encode()).hexdigest()
            return {"id": int(hash_val[:8], 16), "name": repo_name,
                    "full_name": f"{repo_owner}/{repo_name}",
                    "owner": {"login": repo_owner, "type": "User"},
                    "private": False,
                    "stars": int(hash_val[8:16], 16) % 50000,
                    "forks": int(hash_val[16:24], 16) % 5000,
                    "object": "repository"}

        return self._request(
            "GET", f"{self.BASE_URL}/repos/{repo_owner}/{repo_name}",
            extra_headers={"Accept": "application/vnd.github+json",
                           "X-GitHub-Api-Version": "2022-11-28"})


class SlackClientWrapper(_BearerAPIWrapper):
    """Thin Slack wrapper spending the OAuth token against slack.com/api.

    For full typed Slack support use scrapyard.connectors.slack_client_wrapper.
    """

    BASE_URL = "https://slack.com/api"

    def send_message(self, channel: str, text: str) -> dict:
        """Post a message via chat.postMessage; deterministic sample offline."""
        if not channel:
            raise ValueError("channel is required")
        if not text:
            raise ValueError("text is required")

        if self.oauth.offline:
            self.oauth.get_access_token()
            ts = f"{int(time.time())}.{hashlib.sha256(text.encode()).hexdigest()[:6]}"
            return {"ok": True, "channel": channel, "ts": ts,
                    "message": {"type": "message", "text": text, "ts": ts},
                    "object": "chat.postMessage"}

        return self._request("POST", f"{self.BASE_URL}/chat.postMessage",
                             json_body={"channel": channel, "text": text})


def _selftest():
    """Offline selftest: token flow, webhook HMAC, wrappers - zero network I/O."""
    # --- OAuth2 offline token flow
    client = OAuth2ClientCredentials("test_client_id", "test_client_secret",
                                     "https://oauth.example.com/token", offline=True)
    token1 = client.get_access_token()
    assert isinstance(token1, str) and token1.startswith("offline_token_")
    # secret must never leak into token material
    assert "test_client_secret" not in token1
    assert client.get_access_token() == token1, "token should be cached"
    token2 = client.refresh_token()
    assert token2 != token1, "refreshed token should differ"
    assert client.auth_header() == {"Authorization": f"Bearer {token2}"}

    # Offline tokens are deterministic given (client_id, counter)
    twin = OAuth2ClientCredentials("test_client_id", "another_secret",
                                   "https://oauth.example.com/token", offline=True)
    assert twin.get_access_token() == token1, \
        "offline token must depend on client_id+counter only, never the secret"

    # Validation errors
    for args in [("", "s", "u"), ("i", "", "u"), ("i", "s", "")]:
        try:
            OAuth2ClientCredentials(*args)
            raise AssertionError(f"should reject {args}")
        except ValueError:
            pass

    # --- Real token-endpoint wiring via a stub session (no network)
    captured = {}

    class _StubResp:
        status_code = 200
        content = b"x"
        text = ""

        @staticmethod
        def json():
            return {"access_token": "real_tok_abc", "expires_in": 120,
                    "token_type": "Bearer"}

    class _StubSession:
        def post(self, url, **kwargs):
            captured.update(url=url, **kwargs)
            return _StubResp()

    real = OAuth2ClientCredentials("cid", "csec", "https://issuer/token",
                                   scope="read:all", session=_StubSession())
    tok = real.get_access_token()
    assert tok == "real_tok_abc"
    assert captured["url"] == "https://issuer/token"
    assert captured["auth"] == ("cid", "csec"), "client auth must be HTTP basic"
    assert captured["data"]["grant_type"] == "client_credentials"
    assert captured["data"]["scope"] == "read:all"
    assert not real._token_data.is_expired()

    class _FailSession:
        def post(self, url, **kwargs):
            r = _StubResp()
            r.status_code = 401
            r.text = "invalid_client"
            return r

    bad = OAuth2ClientCredentials("cid", "wrong", "https://issuer/token",
                                  session=_FailSession())
    try:
        bad.get_access_token()
        raise AssertionError("401 from token endpoint must raise")
    except TokenRefreshError as e:
        assert "401" in str(e)

    # --- Webhook signature verification
    secret = "whsec_test_secret_key"
    payload = b'{"event": "test", "data": "value"}'
    valid_sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(payload, valid_sig, secret) is True
    assert verify_webhook_signature(payload, f"sha256={valid_sig}", secret) is True
    assert verify_webhook_signature(payload, "invalid_sig", secret) is False
    assert verify_webhook_signature(payload, valid_sig, "wrong_secret") is False

    receiver = WebhookReceiver(secret)
    assert receiver.verify(payload, valid_sig) is True
    assert receiver.verify(payload, "bad_sig") is False
    try:
        verify_webhook_signature("not bytes", "sig", secret)
        raise AssertionError("non-bytes payload must raise TypeError")
    except TypeError:
        pass
    try:
        WebhookReceiver("")
        raise AssertionError("empty secret must raise")
    except ValueError:
        pass

    # --- API wrappers in offline mode
    oauth = OAuth2ClientCredentials("test_id", "test_secret", "http://test",
                                    offline=True)
    stripe = StripeClientWrapper(oauth)
    charge = stripe.create_charge(1000, "usd", "cus_123")
    assert charge["amount"] == 1000 and charge["currency"] == "usd"
    assert charge["customer"] == "cus_123" and charge["status"] == "succeeded"
    assert charge["id"].startswith("ch_offline_")
    try:
        stripe.create_charge(-100, "usd", "cus_123")
        raise AssertionError("negative amount must raise")
    except ValueError:
        pass
    try:
        stripe.create_charge(100, "US", "cus_123")
        raise AssertionError("bad currency must raise")
    except ValueError:
        pass

    github = GitHubClientWrapper(oauth)
    repo = github.get_repo_info("octocat", "Hello-World")
    assert repo["name"] == "Hello-World"
    assert repo["owner"]["login"] == "octocat"
    assert repo["full_name"] == "octocat/Hello-World"
    assert "stars" in repo and "forks" in repo
    try:
        github.get_repo_info("", "repo")
        raise AssertionError("empty owner must raise")
    except ValueError:
        pass

    slack = SlackClientWrapper(oauth)
    msg = slack.send_message("#general", "Hello, world!")
    assert msg["ok"] is True and msg["channel"] == "#general"
    assert msg["message"]["text"] == "Hello, world!"
    for bad in [("", "text"), ("#general", "")]:
        try:
            slack.send_message(*bad)
            raise AssertionError(f"should reject {bad}")
        except ValueError:
            pass

    print("oauth2_client_credentials selftest: all tests passed")


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(1 if _selftest() is False else 0)
