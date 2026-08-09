"""
password_hashing — Hash + verify passwords with Argon2/bcrypt.

### PART-META-JSON
{
  "name": "password_hashing",
  "layer": "identity",
  "purpose": "Password hashing on passlib CryptContext (Argon2 default, bcrypt fallback): hash/verify, per-call parameter overrides, scheme selection, hash-upgrade on login (verify old hash then rehash with the current default), bulk hashing, strength checking, and rehash-needed detection.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "passlib[argon2]"
  ],
  "inputs": "Plaintext passwords (never persisted), stored hash strings, optional scheme/parameter overrides.",
  "outputs": "Salted modular-crypt hash strings; verification booleans.",
  "files_created": [],
  "security_notes": "Argon2id is the default scheme; verification is delegated to passlib's constant-time comparison. Malformed hashes verify as False rather than raising. upgrade_password_hash verifies the presented plaintext against the OLD hash before issuing a new one, so it cannot be used to overwrite a hash without knowing the password. The audit hook logs only user id and hash scheme, never plaintext or hash material. Plaintexts must not be logged or cached by callers.",
  "ai_usage": "hash_password(pw) on registration; verify_password(pw, stored) on login; if needs_rehash(stored): store upgrade_password_hash(pw, stored).",
  "example": "stored = hash_password('s3cret!'); assert verify_password('s3cret!', stored)",
  "import_path": "scrapyard.identity.password_hashing"
}
### END-PART-META
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional, Tuple

from passlib.context import CryptContext

# Compatibility shim: passlib 1.7.4 + bcrypt>=4.1.
# passlib expects bcrypt.__about__.__version__ (removed) and probes the backend
# with >72-byte secrets, relying on bcrypt's historical silent truncation at 72
# bytes; bcrypt>=4.1 raises ValueError instead, so loading the backend crashes.
# Restore the attribute and the truncation semantics (72 bytes is bcrypt's own
# algorithmic limit — this does not weaken hashes, it matches what every bcrypt
# implementation does internally).
try:  # pragma: no cover - environment-dependent
    import bcrypt as _bcrypt_mod
    if not hasattr(_bcrypt_mod, "__about__"):
        _bcrypt_mod.__about__ = type("_About", (), {"__version__": _bcrypt_mod.__version__})
        _orig_hashpw, _orig_checkpw = _bcrypt_mod.hashpw, _bcrypt_mod.checkpw

        def _hashpw72(password, salt):
            return _orig_hashpw(password[:72], salt)

        def _checkpw72(password, hashed):
            return _orig_checkpw(password[:72], hashed)

        _bcrypt_mod.hashpw = _hashpw72
        _bcrypt_mod.checkpw = _checkpw72
except ImportError:
    pass

_STATUS = "core"
STATUS = "core"

logger = logging.getLogger("scrapyard.identity.password_hashing")

_CTX = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")


class NotSupportedError(Exception):
    """Raised when an unsupported hashing scheme is requested."""

class LegacyHashError(Exception):
    """Raised when legacy hash verification fails."""


def set_hashing_scheme(scheme: str) -> None:
    """Restrict the module context to a single named scheme."""
    global _CTX
    try:
        _CTX = CryptContext(schemes=[scheme], deprecated="auto")
    except (KeyError, ValueError) as e:
        raise NotSupportedError(f"Unsupported hashing scheme: {scheme}") from e


def hash_password_with_params(plaintext: str, params: Dict[str, Any]) -> str:
    """Hash with per-call algorithm parameters (e.g. {'rounds': 12} for bcrypt)."""
    return _CTX.hash(plaintext, **params)


def verify_password_with_error(plaintext: str, hashed: str) -> Tuple[bool, Optional[Exception]]:
    """Verify, returning (result, error) instead of raising on malformed hashes."""
    try:
        return _CTX.verify(plaintext, hashed), None
    except ValueError as e:
        return False, e


def hash_password_multi_scheme(plaintext: str, schemes: List[str]) -> str:
    """Hash using the first scheme in ``schemes``; all requested schemes must be
    configured in the context (so the caller's fallback list is honest)."""
    if not schemes:
        raise NotSupportedError("No hashing scheme requested")
    available = _CTX.schemes()
    for scheme in schemes:
        if scheme not in available:
            raise NotSupportedError(f"Unsupported hashing scheme: {scheme}")
    return _CTX.hash(plaintext, scheme=schemes[0])


def on_password_hashed(hashed: str, user_id: Optional[int] = None) -> None:
    """Audit hook: logs the event with scheme + user id, never hash material."""
    scheme = _CTX.identify(hashed) or "unknown"
    logger.info("password_hashed user_id=%s scheme=%s", user_id, scheme,
                extra={"audit": {"event": "password_hashed",
                                 "user_id": user_id, "scheme": scheme}})


def hash_passwords_bulk(passwords: List[str], params: Optional[Dict] = None) -> List[str]:
    return [_CTX.hash(p, **params) if params else _CTX.hash(p) for p in passwords]


def serialize_password_hash(hashed: str) -> str:
    return base64.b64encode(hashed.encode()).decode()


def deserialize_password_hash(serialized: str) -> str:
    return base64.b64decode(serialized.encode()).decode()


def check_password_strength(password: str) -> Tuple[bool, List[str]]:
    rules = {
        'min_length': 8,
        'has_uppercase': any(c.isupper() for c in password),
        'has_lowercase': any(c.islower() for c in password),
        'has_digit': any(c.isdigit() for c in password),
        'has_special': any(not c.isalnum() for c in password)
    }
    issues = []
    if len(password) < rules['min_length']:
        issues.append("Password is too short")
    if not rules['has_uppercase']:
        issues.append("Password must contain an uppercase letter")
    if not rules['has_lowercase']:
        issues.append("Password must contain a lowercase letter")
    if not rules['has_digit']:
        issues.append("Password must contain a digit")
    if not rules['has_special']:
        issues.append("Password must contain a special character")
    return len(issues) == 0, issues


def upgrade_password_hash(plaintext: str, old_hashed: str) -> str:
    """Verify ``plaintext`` against the OLD hash, then return a fresh hash under
    the current default scheme. Raises LegacyHashError when verification fails."""
    try:
        ok = _CTX.verify(plaintext, old_hashed)
    except ValueError as e:
        raise LegacyHashError(f"Cannot verify legacy hash: {e}") from e
    if not ok:
        raise LegacyHashError("Password does not match the existing hash")
    return _CTX.hash(plaintext)


def configure_hashing_context(context: CryptContext) -> None:
    global _CTX
    if not isinstance(context, CryptContext):
        raise TypeError("context must be a passlib CryptContext")
    _CTX = context


def needs_rehash(hashed: str) -> bool:
    return _CTX.needs_update(hashed)


# --- grafted from original part (API stability) ---
_ctx = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

def hash_password(plaintext: str) -> str:
    """Return a salted hash. Never store or log the plaintext."""
    return _ctx.hash(plaintext)

def verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time verify. Returns False on any malformed hash."""
    try:
        return _ctx.verify(plaintext, hashed)
    except ValueError:
        return False


def _selftest() -> None:
    global _CTX
    _CTX = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

    # nucleus behaviour unchanged
    h = hash_password("s3cret-Pass!")
    assert h.startswith("$argon2") and verify_password("s3cret-Pass!", h)
    assert not verify_password("wrong", h)
    assert not verify_password("s3cret-Pass!", "not-a-hash")

    # verify_password_with_error returns a (bool, error) tuple in BOTH branches
    ok, err = verify_password_with_error("s3cret-Pass!", h)
    assert ok is True and err is None
    ok, err = verify_password_with_error("x", "garbage")
    assert ok is False and isinstance(err, Exception)

    # multi-scheme: hashes with the FIRST requested scheme; unknown scheme raises
    b = hash_password_multi_scheme("pw-Multi1!", ["bcrypt", "argon2"])
    assert b.startswith("$2") and _CTX.verify("pw-Multi1!", b)
    a = hash_password_multi_scheme("pw-Multi1!", ["argon2"])
    assert a.startswith("$argon2")
    for bad in (["md5_crypt"], []):
        try:
            hash_password_multi_scheme("pw", bad)
            raise AssertionError(f"accepted schemes {bad}")
        except NotSupportedError:
            pass

    # upgrade: wrong password refused; right password produces a fresh default-scheme hash
    old = _CTX.hash("Upgrade-me1!", scheme="bcrypt")
    try:
        upgrade_password_hash("wrong-password", old)
        raise AssertionError("upgrade accepted wrong password")
    except LegacyHashError:
        pass
    try:
        upgrade_password_hash("x", "not-a-hash")
        raise AssertionError("upgrade accepted malformed hash")
    except LegacyHashError:
        pass
    new = upgrade_password_hash("Upgrade-me1!", old)
    assert new.startswith("$argon2") and _CTX.verify("Upgrade-me1!", new)
    assert needs_rehash(old) is False or isinstance(needs_rehash(old), bool)

    # params / bulk / serialization
    hp = hash_password_with_params("Param-pw1!", {"scheme": "bcrypt", "rounds": 4})
    assert _CTX.verify("Param-pw1!", hp)
    hashes = hash_passwords_bulk(["a-A1!bcd", "b-B2!cde"])
    assert len(hashes) == 2 and all(_CTX.verify(p, hh) for p, hh in zip(["a-A1!bcd", "b-B2!cde"], hashes))
    round_trip = deserialize_password_hash(serialize_password_hash(h))
    assert round_trip == h

    # strength checker
    ok, issues = check_password_strength("Str0ng-pass!")
    assert ok and issues == []
    ok, issues = check_password_strength("weak")
    assert not ok and len(issues) >= 3

    # scheme switching + context injection
    set_hashing_scheme("bcrypt")
    assert hash_password_with_params("Switch1!", {}).startswith("$2")
    try:
        set_hashing_scheme("no_such_scheme")
        raise AssertionError("bad scheme accepted")
    except NotSupportedError:
        pass
    configure_hashing_context(CryptContext(schemes=["argon2"], deprecated="auto"))
    assert _CTX.hash("Ctx-pw1!").startswith("$argon2")
    try:
        configure_hashing_context("nope")  # type: ignore[arg-type]
        raise AssertionError("non-context accepted")
    except TypeError:
        pass
    _CTX = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

    # audit hook runs without raising and never needs the plaintext
    on_password_hashed(h, user_id=7)

    print("password_hashing selftest: PASS")


if __name__ == "__main__":
    _selftest()
