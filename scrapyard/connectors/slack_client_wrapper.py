"""
slack_client_wrapper — Wraps the Slack Web API (slack.com/api) with real HTTP execution
(httpx async, requests sync), typed responses, error mapping, and an explicit offline
mode for tests.

### PART-META-JSON
{
  "name": "slack_client_wrapper",
  "layer": "connectors",
  "purpose": "Sends messages and makes generic Slack Web API calls against https://slack.com/api with bearer-token auth: async via httpx (send_message/api_call), sync via requests (send_message_sync), Slack's ok/error envelope mapped to a typed SlackResponse, and rate-limit/HTTP failures surfaced honestly. An explicit offline=True mode serves caller-queued plain-dict Slack envelopes so selftests run without network.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "httpx (async path)",
    "requests (sync path)"
  ],
  "inputs": "Slack bot/user OAuth token (xoxb-/xoxp-), channel IDs or names, message text/payloads, arbitrary Web API method names; offline flag plus queued envelopes for tests.",
  "outputs": "SlackResponse (status, error, data with Slack's raw envelope) and raw dict envelopes from api_call.",
  "files_created": [],
  "security_notes": "Handles live Slack OAuth tokens: sent only in the Authorization header over TLS and never logged. Message text is delivered to real workspaces in real mode - a bug or attacker-controlled channel/text means workspace spam or data exfiltration into Slack, so validate channel targets from untrusted input. Slack error strings (e.g. channel_not_found) are safe to log; response payloads may contain workspace metadata, treat accordingly. Offline mode does zero network I/O and is for tests only. Honors HTTP 429 by raising with the retry_after hint rather than silently retrying.",
  "ai_usage": "async: await SlackClientWrapper(token).send_message('#chan', 'hi'); sync: SlackClientWrapper(token).send_message_sync(...). Tests: SlackClientWrapper(token, offline=True).queue_offline_response({'ok': True}).",
  "example": "from scrapyard.connectors.slack_client_wrapper import SlackClientWrapper",
  "import_path": "scrapyard.connectors.slack_client_wrapper"
}
### END-PART-META
"""

from typing import Optional, List, Dict, Any
import asyncio
import logging

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://slack.com/api"
DEFAULT_TIMEOUT = 30.0


class SlackAPIError(Exception):
    """Raised for transport-level or protocol-level Slack API failures."""


class SlackRateLimitError(SlackAPIError):
    """Raised on HTTP 429 from Slack; carries retry_after seconds when known."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class SlackResponse:
    """Typed view over Slack's {ok, error, ...} envelope."""

    def __init__(self, status: bool, error: Optional[str] = None,
                 data: Optional[Dict[str, Any]] = None):
        self.status = status
        self.error = error
        self.data = data or {}

    @classmethod
    def from_envelope(cls, envelope: Dict[str, Any]) -> "SlackResponse":
        ok = bool(envelope.get("ok"))
        return cls(status=ok,
                   error=None if ok else envelope.get("error", "unknown_error"),
                   data=envelope)

    def __repr__(self) -> str:
        return f"SlackResponse(status={self.status}, error={self.error!r})"


class SlackClientWrapper:
    """Slack Web API client with real HTTP paths and an explicit offline mode.

    Real mode POSTs to {base_url}/{method} with bearer auth (httpx for async,
    requests for sync). offline=True consumes envelopes queued via
    queue_offline_response() in FIFO order - tests only, zero network I/O.
    """

    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL, *,
                 timeout: float = DEFAULT_TIMEOUT, offline: bool = False):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.offline = offline
        self._offline_queue: List[Dict[str, Any]] = []

    # -- offline seeding ----------------------------------------------------------
    def queue_offline_response(self, envelope: Dict[str, Any]) -> "SlackClientWrapper":
        """Queue a Slack envelope dict ({'ok': bool, ...}) for offline mode."""
        self._offline_queue.append(envelope)
        return self

    def _next_offline(self, api_method: str) -> Dict[str, Any]:
        if not self._offline_queue:
            raise SlackAPIError(
                f"offline mode: no queued response for {api_method}")
        return self._offline_queue.pop(0)

    # -- shared plumbing ----------------------------------------------------------
    def _require_token(self) -> None:
        if not self.token:
            raise SlackAPIError("Invalid token provided.")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    @staticmethod
    def _check_http(status_code: int, headers: Dict[str, str], api_method: str) -> None:
        if status_code == 429:
            try:
                retry_after = float(headers.get("Retry-After", ""))
            except ValueError:
                retry_after = None
            raise SlackRateLimitError(
                f"Slack rate limit hit on {api_method}", retry_after)
        if status_code != 200:
            raise SlackAPIError(
                f"Slack API HTTP {status_code} on {api_method}")

    # -- async real path ----------------------------------------------------------
    async def api_call(self, api_method: str,
                       payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """POST to a Slack Web API method; returns the raw envelope dict."""
        self._require_token()
        if self.offline:
            return self._next_offline(api_method)
        import httpx  # deferred: offline/sync users never need it
        url = f"{self.base_url}/{api_method.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, headers=self._headers(),
                                         json=payload or {})
        except httpx.HTTPError as exc:
            raise SlackAPIError(f"network error on {api_method}: {exc}") from exc
        self._check_http(resp.status_code, dict(resp.headers), api_method)
        return resp.json()

    async def send_message(self, channel: str, text: str,
                           user: Optional[str] = None) -> SlackResponse:
        """Send a message via chat.postMessage (chat.postEphemeral when user given)."""
        if not channel or not text:
            raise SlackAPIError("channel and text are required")
        payload: Dict[str, Any] = {"channel": channel, "text": text}
        api_method = "chat.postMessage"
        if user:
            payload["user"] = user
            api_method = "chat.postEphemeral"
        envelope = await self.api_call(api_method, payload)
        return SlackResponse.from_envelope(envelope)

    # -- sync real path -----------------------------------------------------------
    def api_call_sync(self, api_method: str,
                      payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Synchronous variant of api_call using requests."""
        self._require_token()
        if self.offline:
            return self._next_offline(api_method)
        import requests
        url = f"{self.base_url}/{api_method.lstrip('/')}"
        try:
            resp = requests.post(url, headers=self._headers(), json=payload or {},
                                 timeout=self.timeout)
        except requests.RequestException as exc:
            raise SlackAPIError(f"network error on {api_method}: {exc}") from exc
        self._check_http(resp.status_code, dict(resp.headers), api_method)
        return resp.json()

    def send_message_sync(self, channel: str, text: str,
                          user: Optional[str] = None) -> SlackResponse:
        """Synchronous send_message."""
        if not channel or not text:
            raise SlackAPIError("channel and text are required")
        payload: Dict[str, Any] = {"channel": channel, "text": text}
        api_method = "chat.postMessage"
        if user:
            payload["user"] = user
            api_method = "chat.postEphemeral"
        return SlackResponse.from_envelope(self.api_call_sync(api_method, payload))

    # -- context manager ----------------------------------------------------------
    def __enter__(self) -> "SlackClientWrapper":
        return self

    def __exit__(self, *exc_info) -> None:
        # No persistent network client is retained, but queued offline fixtures
        # may contain response data and should not leak across context lifetimes.
        self._offline_queue.clear()


def _selftest():
    """Offline-mode selftest: no network I/O."""

    async def run_tests():
        # Successful send (offline envelope)
        client = SlackClientWrapper(token="xoxb-offline", offline=True)
        client.queue_offline_response({"ok": True, "ts": "12345.678"})
        response = await client.send_message(channel="#general", text="Hello World!")
        assert response.status is True and response.error is None
        assert response.data["ts"] == "12345.678"

        # Empty token raises before any I/O
        try:
            await SlackClientWrapper(token="", offline=True).send_message(
                channel="#general", text="Hello World!")
            raise AssertionError("empty token must raise")
        except SlackAPIError as e:
            assert str(e) == "Invalid token provided."

        # Slack-level error envelope (rate limited)
        client.queue_offline_response({"ok": False, "error": "ratelimited"})
        response = await client.send_message(channel="#general", text="Hello!")
        assert response.status is False and response.error == "ratelimited"

        # Ephemeral routing when user is given
        client.queue_offline_response({"ok": True})
        resp = await client.send_message("#ops", "psst", user="U123")
        assert resp.status is True

        # Missing channel/text validation
        try:
            await client.send_message("", "text")
            raise AssertionError("empty channel must raise")
        except SlackAPIError:
            pass

        # Unqueued offline call is an honest error, not fabricated success
        try:
            await client.api_call("chat.postMessage", {"channel": "#x", "text": "y"})
            raise AssertionError("unqueued offline call must raise")
        except SlackAPIError as e:
            assert "no queued response" in str(e)

        # Generic api_call passthrough
        client.queue_offline_response({"ok": True, "channels": [{"id": "C1"}]})
        env = await client.api_call("conversations.list")
        assert env["channels"][0]["id"] == "C1"

        # Context manager
        with SlackClientWrapper(token="xoxb-offline", offline=True) as cm:
            cm.queue_offline_response({"ok": True})
            r = await cm.send_message(channel="#test", text="Test")
            assert r.status is True

    asyncio.run(run_tests())

    # Sync path (offline)
    sclient = SlackClientWrapper(token="xoxb-sync", offline=True)
    sclient.queue_offline_response({"ok": False, "error": "channel_not_found"})
    r = sclient.send_message_sync("#nope", "hi")
    assert r.status is False and r.error == "channel_not_found"

    # HTTP status mapping (429 with Retry-After)
    try:
        SlackClientWrapper._check_http(429, {"Retry-After": "12"}, "chat.postMessage")
        raise AssertionError("429 must raise")
    except SlackRateLimitError as e:
        assert e.retry_after == 12.0
    try:
        SlackClientWrapper._check_http(500, {}, "chat.postMessage")
        raise AssertionError("500 must raise")
    except SlackAPIError:
        pass

    print("slack_client_wrapper selftest: all tests passed")


if __name__ == "__main__":
    _selftest()
