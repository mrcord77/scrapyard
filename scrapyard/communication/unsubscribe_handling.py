"""
unsubscribe_handling — Honor unsubscribe + suppression list.

### PART-META-JSON
{
  "name": "unsubscribe_handling",
  "layer": "communication",
  "purpose": "Honor unsubscribe + suppression list.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_unsubscribe_token(email, secret, salt); verify_unsubscribe_token(email, token, secret, salt); get_suppressed_emails(session, limit, offset); bulk_suppress_emails(session, emails); bulk_unsuppress_emails(session, emails); SuppressionListModel(...); AlreadySuppressedError(...); InvalidTokenError(...) (plus more).",
  "outputs": "Returns: create_unsubscribe_token -> str; verify_unsubscribe_token -> bool; get_suppressed_emails -> List[str]; bulk_suppress_emails -> Tuple[int, int]; bulk_unsuppress_emails -> Tuple[int, int].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Makes outbound network calls; set timeouts, validate URLs/hosts, and never send secrets to untrusted endpoints. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `create_unsubscribe_token` from `scrapyard.communication.unsubscribe_handling` and call it as shown in `example`; run `py -m scrapyard.communication.unsubscribe_handling` to see its offline selftest.",
  "example": "from scrapyard.communication.unsubscribe_handling import create_unsubscribe_token",
  "import_path": "scrapyard.communication.unsubscribe_handling"
}
### END-PART-META
"""
from __future__ import annotations
import hmac
import hashlib
from typing import Optional, List, Tuple, Union, Dict, Set, TypeVar, Generic, TYPE_CHECKING
from datetime import timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select
from fastapi import HTTPException
from pydantic import BaseModel
from cryptography.fernet import Fernet
from jinja2 import Template

STATUS = "core"

import base64
import logging

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel

log = logging.getLogger("scrapyard.unsubscribe")


class SuppressionListModel(IntPKModel):
    """Persistent suppression list entry (real model, replaces the phantom
    TYPE_CHECKING-only import that crashed every query at runtime)."""

    __tablename__ = "unsubscribe_suppression"
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)

class AlreadySuppressedError(Exception):
    pass

class InvalidTokenError(Exception):
    pass

class UnsubscribeAttemptLog(BaseModel):
    email: str
    success: bool
    error: Optional[str]

def _fernet_for_secret(secret: str) -> Fernet:
    """Derive a stable Fernet key from the shared secret (the old code generated
    a fresh random key on every call, so no token could ever verify)."""
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def create_unsubscribe_token(email: str, secret: str, salt: Optional[str] = None) -> str:
    if not email or not secret:
        raise ValueError("Email or secret cannot be empty")
    payload = (email.lower() + "\x00" + (salt or "")).encode()
    return _fernet_for_secret(secret).encrypt(payload).decode()


def verify_unsubscribe_token(email: str, token: str, secret: str, salt: Optional[str] = None) -> bool:
    if not email or not secret or not token:
        return False
    try:
        payload = _fernet_for_secret(secret).decrypt(token.encode()).decode()
    except Exception:
        return False
    got_email, _, got_salt = payload.partition("\x00")
    return got_email == email.lower() and got_salt == (salt or "")

class SuppressionList:
    def __init__(self) -> None:
        self._s: Set[str] = set()

    def suppress(self, email: str) -> None:
        if not email:
            raise ValueError("Email cannot be empty")
        self._s.add(email.lower())

    def is_suppressed(self, email: str) -> bool:
        return email.lower() in self._s

def get_suppressed_emails(session: Session, limit: int = 100, offset: int = 0) -> List[str]:
    query = select(SuppressionListModel.email).offset(offset).limit(limit)
    # scalars() already yields plain email strings (the old row[0] sliced
    # the first character of each address).
    return list(session.execute(query).scalars().all())

def bulk_suppress_emails(session: Session, emails: List[str]) -> Tuple[int, int]:
    added_count = 0
    already_present_count = 0
    for email in emails:
        if not email:
            raise ValueError("Email cannot be empty")
        if session.query(SuppressionListModel).filter_by(email=email.lower()).first():
            already_present_count += 1
        else:
            suppression_list_model = SuppressionListModel(email=email.lower())
            session.add(suppression_list_model)
            added_count += 1
    session.commit()
    return (added_count, already_present_count)

def bulk_unsuppress_emails(session: Session, emails: List[str]) -> Tuple[int, int]:
    removed_count = 0
    not_found_count = 0
    for email in emails:
        if not email:
            raise ValueError("Email cannot be empty")
        suppression_list_model = session.query(SuppressionListModel).filter_by(email=email.lower()).first()
        if suppression_list_model:
            session.delete(suppression_list_model)
            removed_count += 1
        else:
            not_found_count += 1
    session.commit()
    return (removed_count, not_found_count)

def is_email_suppressed(session: Session, email: str) -> bool:
    if not email:
        raise ValueError("Email cannot be empty")
    return session.query(SuppressionListModel).filter_by(email=email.lower()).first() is not None

def log_unsubscribe_attempt(email: str, success: bool, error: Optional[str] = None) -> UnsubscribeAttemptLog:
    entry = UnsubscribeAttemptLog(email=email, success=success, error=error)
    log.info("unsubscribe attempt email=%s success=%s error=%s", email, success, error)
    return entry

def get_unsubscribe_token_expiration(config: Dict) -> timedelta:
    return config.get('unsubscribe_token_expiration', timedelta(hours=24))

def get_suppression_list_size(session: Session) -> int:
    return session.query(SuppressionListModel).count()

def generate_unsubscribe_link(email: str, base_url: str, secret: str) -> str:
    from urllib.parse import urlencode
    token = create_unsubscribe_token(email, secret)
    return f"{base_url}/unsubscribe?" + urlencode({"email": email, "token": token})

# --- grafted from original part (API stability) ---
def unsubscribe_token(email: str, secret: str) -> str:
    return hmac.new(secret.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:32]

def verify_unsubscribe(email: str, token: str, secret: str) -> bool:
    return hmac.compare_digest(unsubscribe_token(email, secret), token)


def _selftest() -> None:
    """Offline self-test: token round-trip and suppression list."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S

    secret = "s3cret"
    tok = create_unsubscribe_token("User@Example.com", secret, salt="x")
    assert verify_unsubscribe_token("user@example.com", tok, secret, salt="x") is True
    assert verify_unsubscribe_token("user@example.com", tok, secret, salt="y") is False
    assert verify_unsubscribe_token("other@example.com", tok, secret, salt="x") is False
    assert verify_unsubscribe_token("user@example.com", tok, "wrong", salt="x") is False
    assert verify_unsubscribe_token("user@example.com", "garbage", secret) is False
    try:
        create_unsubscribe_token("", secret)
        raise AssertionError("empty email must raise")
    except ValueError:
        pass

    # HMAC-style token (grafted API) still verifies
    t2 = unsubscribe_token("a@b.c", secret)
    assert verify_unsubscribe("a@b.c", t2, secret) is True
    assert verify_unsubscribe("a@b.c", t2, "nope") is False

    link = generate_unsubscribe_link("u+tag@example.com", "https://x.io", secret)
    assert link.startswith("https://x.io/unsubscribe?") and "u%2Btag%40example.com" in link

    # In-memory suppression helper
    sl = SuppressionList()
    sl.suppress("Someone@Example.com")
    assert sl.is_suppressed("someone@example.com") is True

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with _S(engine) as db:
                added, present = bulk_suppress_emails(db, ["A@x.io", "b@x.io"])
                assert (added, present) == (2, 0)
                added, present = bulk_suppress_emails(db, ["a@x.io", "c@x.io"])
                assert (added, present) == (1, 1)
                assert is_email_suppressed(db, "A@X.IO") is True
                assert get_suppression_list_size(db) == 3
                assert sorted(get_suppressed_emails(db)) == ["a@x.io", "b@x.io", "c@x.io"]

                removed, missing = bulk_unsuppress_emails(db, ["a@x.io", "zz@x.io"])
                assert (removed, missing) == (1, 1)
                assert is_email_suppressed(db, "a@x.io") is False

                entry = log_unsubscribe_attempt("a@x.io", True)
                assert entry.success is True
        finally:
            engine.dispose()

    print("unsubscribe_handling self-test passed")


if __name__ == "__main__":
    _selftest()
