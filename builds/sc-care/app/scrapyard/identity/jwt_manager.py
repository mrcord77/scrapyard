"""
jwt_manager — Encode/decode signed access + refresh tokens.

### PART-META-JSON
{
  "name": "jwt_manager",
  "layer": "identity",
  "purpose": "JWT lifecycle: encode/decode signed access + refresh token pairs, refresh-token rotation that reuses verified claims, and a real revocation layer (in-memory store with expiry-based cleanup, pluggable store interface) consulted on every verify path.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "pyjwt"
  ],
  "inputs": "Subject strings, signing secret(s), optional extra claims, previously issued tokens.",
  "outputs": "Signed JWT strings, decoded claim dicts, access+refresh pair dicts.",
  "files_created": [],
  "security_notes": "HS256 by default; decode restricts algorithms to the configured allow-list so alg-confusion downgrades are rejected. Revocation is enforced in decode_token/introspect/rotate paths; the default store is in-process only, so multi-instance deployments must inject a shared RevocationStore or revocation will not propagate. Rotation verifies the old refresh token's signature and type before reusing claims and blacklists it immediately. Tokens are logged only as SHA-256 prefixes, never raw.",
  "ai_usage": "issue_pair(subject, secret) at login; decode_token(token, secret, expected_type='access') per request; rotate_refresh_token on refresh; revoke_token on logout.",
  "example": "pair = issue_pair('user-1', SECRET); claims = decode_token(pair['access_token'], SECRET, expected_type='access')",
  "import_path": "scrapyard.identity.jwt_manager"
}
### END-PART-META
"""
from __future__ import annotations

import base64
import hashlib
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

import jwt

STATUS = "core"

logger = logging.getLogger("scrapyard.identity.jwt_manager")


class TokenRevokedError(Exception):
    pass

class SecretNotFoundError(Exception):
    pass

class InvalidSecretError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _b64url_decode(segment: str) -> bytes:
    """Decode a base64url segment, tolerating any padding variant."""
    seg = segment.rstrip("=")
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def _canonical_token(token: str) -> str:
    """Canonical identity of a JWT, independent of base64 padding.

    PyJWT accepts padding-variant tokens (``token``, ``token+'='``,
    ``token+'=='``) as the SAME token, so revocation must key on identity, not
    the raw string. We first collapse every base64url segment to its
    unpadded canonical form (so all variants map to one string), then prefer a
    stable ``jti`` claim when present. Decoding the already-canonicalized form
    guarantees every variant takes the same path and yields the same key.
    """
    try:
        parts = token.split(".")
        canonical = ".".join(
            base64.urlsafe_b64encode(_b64url_decode(p)).rstrip(b"=").decode("ascii")
            for p in parts
        )
    except Exception:
        canonical = token.rstrip("=")
    try:
        jti = jwt.decode(
            canonical, options={"verify_signature": False, "verify_exp": False}
        ).get("jti")
        if jti is not None:
            return "jti:" + str(jti)
    except jwt.InvalidTokenError:
        pass
    return "raw:" + canonical


def _token_key(token: str) -> str:
    """Stable non-reversible key for a token's IDENTITY (also safe to log).

    Keyed on the canonical token identity, not the raw string, so base64
    padding variants of the same token share one revocation key.
    """
    return hashlib.sha256(_canonical_token(token).encode("utf-8")).hexdigest()


# --- revocation store (real, pluggable) ---

class RevocationStore(Protocol):
    """Interface for revocation backends (in-memory, Redis, DB...)."""
    def revoke(self, key: str, expires_at: datetime) -> None: ...
    def is_revoked(self, key: str) -> bool: ...
    def cleanup(self) -> int: ...


class InMemoryRevocationStore:
    """Thread-safe in-memory revocation set with expiry-based cleanup.

    Entries drop out automatically once the underlying token would have
    expired anyway, so the set cannot grow without bound.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, datetime] = {}
        self._lock = threading.Lock()

    def revoke(self, key: str, expires_at: datetime) -> None:
        with self._lock:
            self._entries[key] = expires_at

    def is_revoked(self, key: str) -> bool:
        self.cleanup()
        with self._lock:
            return key in self._entries

    def cleanup(self) -> int:
        """Drop entries whose token expiry has passed; returns count removed."""
        now = _now()
        with self._lock:
            dead = [k for k, exp in self._entries.items() if exp <= now]
            for k in dead:
                del self._entries[k]
        return len(dead)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_revocation_store: RevocationStore = InMemoryRevocationStore()
_DEFAULT_REVOCATION_TTL_MIN = 60 * 24 * 7  # matches default refresh lifetime


def set_revocation_store(store: RevocationStore) -> None:
    """Inject a shared revocation backend (must implement RevocationStore)."""
    global _revocation_store
    for attr in ("revoke", "is_revoked", "cleanup"):
        if not callable(getattr(store, attr, None)):
            raise TypeError(f"revocation store missing required method {attr!r}")
    _revocation_store = store


def get_revocation_store() -> RevocationStore:
    return _revocation_store


def _token_expiry(token: str) -> datetime:
    """Best-effort expiry read (unverified) used only to bound revocation retention."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
        exp = claims.get("exp")
        if exp is not None:
            return datetime.fromtimestamp(float(exp), tz=timezone.utc)
    except jwt.InvalidTokenError:
        pass
    return _now() + timedelta(minutes=_DEFAULT_REVOCATION_TTL_MIN)


# --- encode / decode ---

def encode_token(subject: str, secret: str, *, expires_minutes: int = 15,
                 token_type: str = "access", extra: Dict[str, Any] | None = None,
                 algorithm: str = "HS256") -> str:
    """Sign a JWT for ``subject`` with an expiry and type claim."""
    payload: Dict[str, Any] = {
        "sub": subject, "type": token_type,
        "iat": _now(), "exp": _now() + timedelta(minutes=expires_minutes),
    }
    if extra:
        payload.update(extra)
    for enricher in _payload_enrichers:
        payload = enricher(payload)
    token = jwt.encode(payload, secret, algorithm=algorithm)
    on_token_issued(token, subject)
    return token


def decode_token(token: str, secret: str, *, algorithms: List[str] | None = None,
                 expected_type: str | None = None) -> Dict[str, Any]:
    """Decode + verify a JWT; rejects revoked tokens. Raises jwt exceptions /
    TokenRevokedError on failure. Enforces required_claims from set_token_policy."""
    if _revocation_store.is_revoked(_token_key(token)):
        raise TokenRevokedError("token has been revoked")
    payload = jwt.decode(token, secret, algorithms=algorithms or list(_allowed_algorithms))
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("expected token type " + repr(expected_type))
    for claim in _token_policy.get("required_claims", []):
        if claim not in payload:
            raise jwt.MissingRequiredClaimError(claim)
    return payload


def issue_pair(subject: str, secret: str, *, access_min: int = 15,
               refresh_min: int = 60 * 24 * 7) -> Dict[str, Any]:
    """Return an access+refresh token pair."""
    return {
        "access_token": encode_token(subject, secret, expires_minutes=access_min, token_type="access"),
        "refresh_token": encode_token(subject, secret, expires_minutes=refresh_min, token_type="refresh"),
        "token_type": "bearer",
    }


def set_allowed_algorithms(algorithms: List[str]) -> None:
    """Set the algorithm allow-list used by decode_token by default."""
    global _allowed_algorithms
    if not algorithms:
        raise ValueError("algorithm allow-list must not be empty")
    _allowed_algorithms = list(algorithms)


def set_token_policy(policy: Dict[str, Any]) -> None:
    """Set token validation policy (currently honoured: required_claims: list[str])."""
    global _token_policy
    _token_policy = dict(policy)


def rotate_refresh_token(refresh_token: str, secret: str) -> str:
    """Verify the old refresh token, blacklist it, and issue a new one reusing
    the verified claims (subject and any custom claims are carried forward)."""
    claims = decode_token(refresh_token, secret, expected_type="refresh")
    blacklist_refresh_token(refresh_token)
    extra = {k: v for k, v in claims.items() if k not in ("sub", "type", "iat", "exp")}
    return encode_token(
        subject=claims["sub"],
        secret=secret,
        expires_minutes=60 * 24 * 7,
        token_type="refresh",
        extra=extra or None,
    )


def add_claim_serializer(serializer: Callable[[Any], Any]) -> None:
    """Register a claim serializer applied by serialize_claims()."""
    _claim_serializers.append(serializer)


def serialize_claims(claims: Dict[str, Any]) -> Dict[str, Any]:
    """Run every registered claim serializer over each claim value."""
    out = dict(claims)
    for serializer in _claim_serializers:
        out = {k: serializer(v) for k, v in out.items()}
    return out


def introspect(token: str, secret: str) -> Dict[str, Any] | None:
    """Return claims (minus exp) for a live, non-revoked token; None otherwise."""
    try:
        payload = decode_token(token, secret)
        return {k: v for k, v in payload.items() if k not in ("secret", "exp")}
    except TokenRevokedError:
        logger.info("introspect: token %s.. is revoked", _token_key(token)[:12])
    except jwt.ExpiredSignatureError:
        logger.info("introspect: token %s.. is expired", _token_key(token)[:12])
    except jwt.InvalidTokenError as e:
        logger.warning("introspect: invalid token %s..: %s", _token_key(token)[:12], e)
    return None


def on_token_issued(token: str, subject: str) -> None:
    """Hook fired when a token is issued (logs a hash prefix, never the token)."""
    logger.info("token_issued subject=%s token=%s..", subject, _token_key(token)[:12])


def on_token_invalidated(token: str) -> None:
    """Hook fired when a token is revoked/blacklisted."""
    logger.info("token_invalidated token=%s..", _token_key(token)[:12])


def encode_tokens(subjects: List[str], secret: str, **kwargs) -> List[str]:
    """Encode multiple tokens in one call."""
    return [encode_token(sub, secret, **kwargs) for sub in subjects]


def set_expiration_policy(policy: Dict[str, Any]) -> None:
    """Store token expiration policy (advisory; read via get_expiration_policy)."""
    global _expiration_policy
    _expiration_policy = dict(policy)


def get_expiration_policy() -> Dict[str, Any]:
    return dict(_expiration_policy)


def revoke_token(token: str, secret: str) -> None:
    """Revoke any token: it will fail decode_token/introspect until it expires."""
    _revocation_store.revoke(_token_key(token), _token_expiry(token))
    on_token_invalidated(token)


def is_token_revoked(token: str, secret: str) -> bool:
    """True if the token has been revoked (consults the revocation store)."""
    return _revocation_store.is_revoked(_token_key(token))


def add_payload_enricher(enricher: Callable[[Dict], Dict]) -> None:
    """Register an enricher applied to every payload before encoding."""
    _payload_enrichers.append(enricher)


def set_secrets(secrets: Dict[str, str]) -> None:
    """Set named secrets for key rotation; use with decode_with_any_secret()."""
    global _secrets
    _secrets = dict(secrets)


def decode_with_any_secret(token: str, **kwargs) -> Dict[str, Any]:
    """Try every secret registered via set_secrets; raises if none verifies."""
    if not _secrets:
        raise SecretNotFoundError("no secrets registered; call set_secrets first")
    last_error: Exception | None = None
    for name, secret in _secrets.items():
        try:
            return decode_token(token, secret, **kwargs)
        except TokenRevokedError:
            raise
        except jwt.InvalidTokenError as e:
            last_error = e
    raise InvalidSecretError(f"no registered secret verified the token: {last_error}")


def blacklist_refresh_token(token: str) -> None:
    """Blacklist a refresh token in the revocation store until it would expire."""
    _revocation_store.revoke(_token_key(token), _token_expiry(token))
    on_token_invalidated(token)


_allowed_algorithms: List[str] = ["HS256"]
_token_policy: Dict[str, Any] = {}
_claim_serializers: List[Callable[[Any], Any]] = []
_expiration_policy: Dict[str, Any] = {}
_payload_enrichers: List[Callable[[Dict], Dict]] = []
_secrets: Dict[str, str] = {}


def _selftest() -> None:
    secret = "selftest-secret-0123456789abcdef0123456789abcdef"
    global _revocation_store, _payload_enrichers, _claim_serializers
    _revocation_store = InMemoryRevocationStore()
    _payload_enrichers = []
    _claim_serializers = []
    set_token_policy({})
    set_allowed_algorithms(["HS256"])

    # round trip + type enforcement
    pair = issue_pair("user-1", secret)
    claims = decode_token(pair["access_token"], secret, expected_type="access")
    assert claims["sub"] == "user-1" and claims["type"] == "access"
    try:
        decode_token(pair["access_token"], secret, expected_type="refresh")
        raise AssertionError("type check missed")
    except jwt.InvalidTokenError:
        pass

    # revocation is real: revoke -> is_token_revoked True -> decode refuses
    assert is_token_revoked(pair["access_token"], secret) is False
    revoke_token(pair["access_token"], secret)
    assert is_token_revoked(pair["access_token"], secret) is True
    try:
        decode_token(pair["access_token"], secret)
        raise AssertionError("revoked token decoded")
    except TokenRevokedError:
        pass
    assert introspect(pair["access_token"], secret) is None

    # EXPLOIT REGRESSION: revocation-bypass via base64 padding variants.
    # PyJWT decodes token, token+'=' and token+'==' as the SAME token; keying
    # revocation on the raw string let the padded variants slip through.
    revoked_tok = pair["access_token"]
    for variant in (revoked_tok, revoked_tok + "=", revoked_tok + "=="):
        assert is_token_revoked(variant, secret) is True, \
            f"padding variant not reported revoked: ...{variant[-3:]!r}"
        try:
            decode_token(variant, secret)
            raise AssertionError(f"revoked padding variant decoded: ...{variant[-3:]!r}")
        except TokenRevokedError:
            pass
        assert introspect(variant, secret) is None, \
            f"revoked padding variant introspected: ...{variant[-3:]!r}"

    # rotation: new token reuses VERIFIED claims (not a base64 segment), old is dead
    old_refresh = encode_token("user-2", secret, token_type="refresh",
                               expires_minutes=60, extra={"tenant": "t1"})
    new_refresh = rotate_refresh_token(old_refresh, secret)
    new_claims = decode_token(new_refresh, secret, expected_type="refresh")
    assert new_claims["sub"] == "user-2" and new_claims["tenant"] == "t1"
    assert is_token_revoked(old_refresh, secret) is True
    # EXPLOIT REGRESSION: the rotated-out token AND its padding variants are all
    # dead — an attacker cannot re-use the old refresh token by re-padding it.
    for variant in (old_refresh, old_refresh + "=", old_refresh + "=="):
        assert is_token_revoked(variant, secret) is True, \
            f"rotated-out padding variant still live: ...{variant[-3:]!r}"
        try:
            decode_token(variant, secret, expected_type="refresh")
            raise AssertionError(f"rotated-out padding variant decoded: ...{variant[-3:]!r}")
        except TokenRevokedError:
            pass
        try:
            rotate_refresh_token(variant, secret)
            raise AssertionError(f"re-rotated a padding variant: ...{variant[-3:]!r}")
        except TokenRevokedError:
            pass
    # rotation refuses access tokens
    access = encode_token("user-2", secret, token_type="access")
    try:
        rotate_refresh_token(access, secret)
        raise AssertionError("rotated an access token")
    except jwt.InvalidTokenError:
        pass

    # expiry-based cleanup: entry for an already-expired token gets purged
    store = InMemoryRevocationStore()
    store.revoke("dead-key", _now() - timedelta(seconds=1))
    store.revoke("live-key", _now() + timedelta(minutes=5))
    assert store.is_revoked("dead-key") is False  # cleaned up
    assert store.is_revoked("live-key") is True
    assert len(store) == 1

    # pluggable store interface is wired into the verify path
    class RecordingStore(InMemoryRevocationStore):
        def __init__(self):
            super().__init__()
            self.checks = 0
        def is_revoked(self, key: str) -> bool:
            self.checks += 1
            return super().is_revoked(key)
    rec = RecordingStore()
    set_revocation_store(rec)
    tok = encode_token("user-3", secret)
    decode_token(tok, secret)
    assert rec.checks >= 1
    try:
        set_revocation_store(object())  # type: ignore[arg-type]
        raise AssertionError("accepted invalid store")
    except TypeError:
        pass
    _revocation_store = InMemoryRevocationStore()

    # policy: required claims enforced
    set_token_policy({"required_claims": ["tenant"]})
    try:
        decode_token(encode_token("u", secret), secret)
        raise AssertionError("required claim not enforced")
    except jwt.MissingRequiredClaimError:
        pass
    assert decode_token(encode_token("u", secret, extra={"tenant": "t"}), secret)["tenant"] == "t"
    set_token_policy({})

    # enrichers + serializers + multi-secret decode
    add_payload_enricher(lambda p: {**p, "enriched": True})
    assert decode_token(encode_token("u", secret), secret)["enriched"] is True
    _payload_enrichers = []
    add_claim_serializer(lambda v: f"<{v}>")
    assert serialize_claims({"a": 1})["a"] == "<1>"
    _claim_serializers = []
    set_secrets({"old": "wrong-secret-0123456789abcdef0123456789abcdef", "new": secret})
    assert decode_with_any_secret(encode_token("u", secret), expected_type="access")["sub"] == "u"
    try:
        decode_with_any_secret(encode_token("u", "unknown-secret-0123456789abcdef0123456789abcdef"))
        raise AssertionError("decoded with unknown secret")
    except InvalidSecretError:
        pass

    # batch + policies
    toks = encode_tokens(["a", "b"], secret, expires_minutes=5)
    assert len(toks) == 2 and decode_token(toks[1], secret)["sub"] == "b"
    set_expiration_policy({"warn_before_expiry": 5})
    assert get_expiration_policy()["warn_before_expiry"] == 5

    print("jwt_manager selftest: PASS")


if __name__ == "__main__":
    _selftest()
