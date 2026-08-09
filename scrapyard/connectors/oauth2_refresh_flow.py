"""
oauth2_refresh_flow — Real OAuth2 refresh-token grant (RFC 6749 §6) with a live token
endpoint POST via requests, SQLite-backed token persistence, and an explicit offline
mode for tests.

### PART-META-JSON
{
  "name": "oauth2_refresh_flow",
  "layer": "connectors",
  "purpose": "Maintains long-lived API access by POSTing grant_type=refresh_token to a real OAuth2 token endpoint (HTTP basic client auth, form-encoded, via requests), persisting the rotated access/refresh tokens with expiry into a caller-chosen SQLite database, and returning the newest unexpired token on demand. An explicit offline=True mode mints deterministic, clearly-fake tokens (never derived from the client_secret) so selftests run with zero network I/O.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "requests",
    "sqlalchemy (model declaration only)",
    "scrapyard.database.base_model"
  ],
  "inputs": "client_id, client_secret, token_url, a refresh token to spend; optional scope, db_path for persistence, offline flag/stub session for tests.",
  "outputs": "Token dicts {access_token, refresh_token, expires_in, token_type}; get_valid_token() returns the stored unexpired token or None.",
  "files_created": [
    "SQLite token store at the caller-supplied db_path (default: oauth2_tokens.db in the system temp directory)."
  ],
  "security_notes": "Persists live access AND refresh tokens to disk in PLAINTEXT SQLite - a refresh token is a long-lived credential, so the default temp-directory location is only acceptable for development; production callers must pass db_path pointing at a directory with restrictive ACLs (or an encrypted volume) and treat the file like a password store. The client_secret is sent only via HTTP basic auth over TLS to token_url and never persisted or logged; offline fake tokens derive from client_id + counter only. Refresh responses that omit a new refresh_token correctly retain the old one (RFC 6749 6). Delete the store file to revoke local state.",
  "ai_usage": "flow = OAuth2RefreshFlow(cid, secret, token_url, db_path=...); flow.refresh(stored_refresh_token); flow.get_valid_token(). Tests: offline=True.",
  "example": "from scrapyard.connectors.oauth2_refresh_flow import OAuth2RefreshFlow",
  "import_path": "scrapyard.connectors.oauth2_refresh_flow"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import hashlib
import logging
import os
import sqlite3
import tempfile

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


class OAuth2RefreshError(Exception):
    """Raised when a token refresh fails."""


class OAuth2Token(IntPKModel):
    """ORM declaration of the token store schema (for SQLAlchemy consumers)."""
    __tablename__ = 'oauth2_refresh_flow_tokens'
    access_token: Mapped[str] = mapped_column(String(255), unique=True)
    refresh_token: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def refresh_token(refresh_token_value: str, client_id: str, client_secret: str,
                  token_url: str, *, scope: Optional[str] = None,
                  timeout: float = DEFAULT_TIMEOUT,
                  session: Optional[Any] = None) -> Dict[str, Any]:
    """Spend a refresh token at a real token endpoint; returns the token response.

    POSTs grant_type=refresh_token with HTTP basic client authentication.
    Raises OAuth2RefreshError on transport or protocol failure.
    """
    if not refresh_token_value:
        raise ValueError("refresh_token_value is required")
    if not client_id or not client_secret:
        raise ValueError("client_id and client_secret are required")
    if not token_url:
        raise ValueError("token_url is required")

    form = {"grant_type": "refresh_token", "refresh_token": refresh_token_value}
    if scope:
        form["scope"] = scope
    sess = session or requests
    try:
        resp = sess.post(token_url, data=form, auth=(client_id, client_secret),
                         timeout=timeout)
    except requests.RequestException as exc:
        raise OAuth2RefreshError(f"network error reaching token endpoint: {exc}") from exc
    if resp.status_code != 200:
        raise OAuth2RefreshError(
            f"token endpoint returned {resp.status_code}: {resp.text[:300]}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise OAuth2RefreshError("token endpoint returned non-JSON body") from exc
    if not body.get("access_token"):
        raise OAuth2RefreshError(
            f"token response missing access_token: {body.get('error', 'unknown')}")
    return {
        "access_token": body["access_token"],
        # RFC 6749 section 6: server MAY omit a new refresh token; keep the old one.
        "refresh_token": body.get("refresh_token", refresh_token_value),
        "expires_in": int(body.get("expires_in", 3600)),
        "token_type": body.get("token_type", "Bearer"),
    }


class OAuth2RefreshFlow:
    """Refresh-token flow with SQLite persistence.

    Real mode calls the token endpoint; offline=True (tests only) mints
    deterministic fake tokens locally without the client_secret.
    """

    def __init__(self, client_id: str, client_secret: str, token_url: str, *,
                 scope: Optional[str] = None,
                 db_path: Optional[str] = None,
                 offline: bool = False,
                 timeout: float = DEFAULT_TIMEOUT,
                 session: Optional[Any] = None):
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required")
        if not token_url:
            raise ValueError("token_url is required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.scope = scope
        self.offline = offline
        self.timeout = timeout
        self._session = session
        self._offline_counter = 0
        self.db_path = db_path or os.path.join(tempfile.gettempdir(),
                                               'oauth2_tokens.db')
        self._initialize_db()

    def _initialize_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS oauth2_refresh_flow_tokens (
                    id INTEGER PRIMARY KEY,
                    access_token TEXT UNIQUE,
                    refresh_token TEXT,
                    expires_at TEXT
                )
            ''')
            conn.commit()

    def _store_token(self, token_data: Dict[str, Any]) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=token_data['expires_in'])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO oauth2_refresh_flow_tokens
                    (access_token, refresh_token, expires_at)
                VALUES (?, ?, ?)
            ''', (token_data['access_token'], token_data['refresh_token'],
                  expires_at.isoformat()))
            conn.commit()

    def get_valid_token(self) -> Optional[Dict[str, Any]]:
        """Return the newest stored token that has not expired, else None."""
        now = datetime.now(timezone.utc)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute('''
                SELECT access_token, refresh_token, expires_at
                FROM oauth2_refresh_flow_tokens
                WHERE expires_at > ?
                ORDER BY id DESC LIMIT 1
            ''', (now.isoformat(),)).fetchone()
        if row is None:
            return None
        expires_at = datetime.fromisoformat(row[2])
        return {
            "access_token": row[0],
            "refresh_token": row[1],
            "expires_in": max(0, int((expires_at - now).total_seconds())),
        }

    # Backwards-compatible alias for the old (broken) accessor name.
    _get_token = get_valid_token

    def _offline_refresh(self) -> Dict[str, Any]:
        """Deterministic fake token pair; client_secret never enters the seed."""
        self._offline_counter += 1
        seed = f"{self.client_id}:{self._offline_counter}"
        digest = hashlib.sha256(seed.encode()).hexdigest()
        return {
            "access_token": f"offline_access_{digest[:24]}",
            "refresh_token": f"offline_refresh_{digest[24:48]}",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    def refresh(self, refresh_token_value: str) -> Dict[str, Any]:
        """Refresh the access token, persist it, and return the token dict."""
        if not refresh_token_value:
            raise ValueError("refresh_token_value is required")
        if self.offline:
            new_token_data = self._offline_refresh()
        else:
            new_token_data = refresh_token(
                refresh_token_value, self.client_id, self.client_secret,
                self.token_url, scope=self.scope, timeout=self.timeout,
                session=self._session)
        self._store_token(new_token_data)
        return new_token_data


def _selftest():
    client_id = 'test_client'
    client_secret = 'test_secret'
    token_url = 'https://example.com/token'

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, 'tokens.db')

        # Offline flow: deterministic fakes, persisted and retrievable
        flow = OAuth2RefreshFlow(client_id, client_secret, token_url,
                                 db_path=db_path, offline=True)
        t1 = flow.refresh('old_refresh_token')
        assert t1['access_token'].startswith('offline_access_')
        assert t1['refresh_token'].startswith('offline_refresh_')
        assert t1['token_type'] == 'Bearer' and t1['expires_in'] == 3600
        assert client_secret not in t1['access_token']

        stored = flow.get_valid_token()
        assert stored is not None
        assert stored['access_token'] == t1['access_token']
        assert 0 < stored['expires_in'] <= 3600

        # A second refresh rotates the token and becomes the newest valid one
        t2 = flow.refresh(t1['refresh_token'])
        assert t2['access_token'] != t1['access_token']
        assert flow.get_valid_token()['access_token'] == t2['access_token']

        # Expired tokens are not returned
        expired_db = os.path.join(tmp, 'expired.db')
        flow2 = OAuth2RefreshFlow(client_id, client_secret, token_url,
                                  db_path=expired_db, offline=True)
        flow2._store_token({"access_token": "dead", "refresh_token": "dead_r",
                            "expires_in": -10})
        assert flow2.get_valid_token() is None

        # Real endpoint wiring via stub session (no network)
        captured = {}

        class _StubResp:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"access_token": "live_at", "expires_in": 900}

        class _StubSession:
            def post(self, url, **kwargs):
                captured.update(url=url, **kwargs)
                return _StubResp()

        real = OAuth2RefreshFlow(client_id, client_secret, token_url,
                                 db_path=os.path.join(tmp, 'real.db'),
                                 session=_StubSession())
        out = real.refresh('rt_original')
        assert out['access_token'] == 'live_at'
        # server sent no new refresh token -> old one retained (RFC 6749 s6)
        assert out['refresh_token'] == 'rt_original'
        assert captured['url'] == token_url
        assert captured['auth'] == (client_id, client_secret)
        assert captured['data'] == {"grant_type": "refresh_token",
                                    "refresh_token": "rt_original"}

        # Protocol failure is an honest error
        class _FailSession:
            def post(self, url, **kwargs):
                r = _StubResp()
                r.status_code = 400
                r.text = "invalid_grant"
                return r

        try:
            refresh_token('bad_rt', client_id, client_secret, token_url,
                          session=_FailSession())
            raise AssertionError("400 from endpoint must raise")
        except OAuth2RefreshError as e:
            assert "400" in str(e)

        # Input validation
        for args in [("", client_id, client_secret, token_url),
                     ("rt", "", client_secret, token_url),
                     ("rt", client_id, client_secret, "")]:
            try:
                refresh_token(*args)
                raise AssertionError(f"should reject {args}")
            except ValueError:
                pass

    # ORM model declaration stays importable with the repaired-forward name
    assert OAuth2Token.__tablename__ == 'oauth2_refresh_flow_tokens'

    print("oauth2_refresh_flow selftest: all tests passed")


if __name__ == "__main__":
    _selftest()
