"""
session_manager — Server-side session issue/lookup/revoke.

### PART-META-JSON
{
  "name": "session_manager",
  "layer": "identity",
  "purpose": "Server-side session issue/lookup/revoke.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: InvalidTokenError(...); SessionAlreadyRevokedError(...); MaxSessionsExceededError(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `InvalidTokenError` from `scrapyard.identity.session_manager` and call it as shown in `example`; run `py -m scrapyard.identity.session_manager` to see its offline selftest.",
  "example": "from scrapyard.identity.session_manager import InvalidTokenError",
  "import_path": "scrapyard.identity.session_manager"
}
### END-PART-META
"""
from __future__ import annotations
import secrets as _secrets
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Callable, Optional
from sqlalchemy import String, Integer, DateTime, Boolean, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.exc import SQLAlchemyError
from fastapi.exceptions import HTTPException
from pydantic.error_wrappers import ValidationError
from scrapyard.database.base_model import IntPKModel

STATUS = "core"

class InvalidTokenError(Exception):
    pass

class SessionAlreadyRevokedError(Exception):
    pass

class MaxSessionsExceededError(Exception):
    pass

class InvalidExpiryTimeError(Exception):
    pass

class SessionNotFoundError(Exception):
    pass

class DatabaseWriteError(Exception):
    pass

class InvalidSortFieldError(Exception):
    pass

class PaginationOutOfBoundsError(Exception):
    pass

class Session(IntPKModel):
    __tablename__ = "sessions"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

class SessionManager:
    def __init__(self, db, ttl_hours: int = 24):
        self.db = db
        self.ttl = ttl_hours

    def create(self, user_id: int) -> str:
        tok = _secrets.token_urlsafe(32)
        self.db.add(Session(user_id=user_id, token=tok,
                            expires_at=datetime.now(timezone.utc) + timedelta(hours=self.ttl)))
        try:
            self.db.flush()
        except SQLAlchemyError as e:
            raise DatabaseWriteError from e
        return tok

    def create_with_expiry(self, user_id: int, expires_at: datetime) -> str:
        if expires_at < datetime.now(timezone.utc):
            raise InvalidExpiryTimeError("Expiry time must be in the future")
        tok = _secrets.token_urlsafe(32)
        self.db.add(Session(user_id=user_id, token=tok, expires_at=expires_at))
        try:
            self.db.flush()
        except SQLAlchemyError as e:
            raise DatabaseWriteError from e
        return tok

    def user_id_for(self, token: str):
        s = self.db.scalars(select(Session).where(Session.token == token)).first()
        if not s or s.revoked:
            return None
        exp = s.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            return None
        return s.user_id

    def list_sessions(self, user_id: int, page: int = 1, per_page: int = 20, sort: str = "created") -> List[Dict]:
        if sort not in ["created", "expires_at"]:
            raise InvalidSortFieldError("Invalid sort field")
        if page < 1 or per_page < 1:
            raise PaginationOutOfBoundsError("Page and per_page must be positive integers")
        query = select(Session).where(Session.user_id == user_id)
        try:
            sessions = self.db.execute(query.order_by(getattr(Session, sort)).offset((page - 1) * per_page).limit(per_page))
        except SQLAlchemyError as e:
            raise DatabaseWriteError from e
        return [{"token": s.token, "user_id": s.user_id, "expires_at": s.expires_at.isoformat(), "revoked": s.revoked} for s in sessions]

    def bulk_revoke(self, tokens: List[str]) -> Dict[str, bool]:
        results = {}
        for token in tokens:
            try:
                self.revoke(token)
                results[token] = True
            except SessionNotFoundError:
                results[token] = False
        return results

    def revoke(self, token: str) -> bool:
        s = self.db.scalars(select(Session).where(Session.token == token)).first()
        if not s or s.revoked:
            raise SessionNotFoundError("Session not found")
        s.revoked = True
        try:
            self.db.flush()
            return True
        except SQLAlchemyError as e:
            raise DatabaseWriteError from e

    def update_expiry(self, token: str, expires_at: datetime) -> bool:
        if expires_at < datetime.now(timezone.utc):
            raise InvalidExpiryTimeError("Expiry time must be in the future")
        s = self.db.scalars(select(Session).where(Session.token == token)).first()
        if not s or s.revoked:
            raise SessionNotFoundError("Session not found")
        s.expires_at = expires_at
        try:
            self.db.flush()
            return True
        except SQLAlchemyError as e:
            raise DatabaseWriteError from e

    def archive_expired(self, max_age_hours: int = 24) -> int:
        expired_threshold = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        query = select(Session).where((Session.expires_at < expired_threshold) & (Session.revoked == False))
        try:
            expired_sessions = self.db.execute(query).scalars().all()
        except SQLAlchemyError as e:
            raise DatabaseWriteError from e
        for s in expired_sessions:
            s.revoked = True
        try:
            self.db.flush()
            return len(expired_sessions)
        except SQLAlchemyError as e:
            raise DatabaseWriteError from e

    def audit_log(self, token: str) -> Optional[Dict]:
        s = self.db.scalars(select(Session).where(Session.token == token)).first()
        if not s or s.revoked:
            return None
        exp = s.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            return None
        return {"token": s.token, "user_id": s.user_id, "expires_at": s.expires_at.isoformat(), "revoked": s.revoked}

    def configure_serializer(self, serializer: Callable[[int], str]) -> None:
        self._serializer = serializer

    def configure_policy(self, max_sessions: int = 10) -> None:
        self.max_sessions = max_sessions

    def add_hook(self, event: str, callback: Callable) -> None:
        if event not in ["create", "revoke"]:
            raise ValueError("Invalid event type")
        setattr(self, f"_{event}_hook", callback)

    def get_session_info(self, token: str) -> Optional[Dict]:
        s = self.db.scalars(select(Session).where(Session.token == token)).first()
        if not s or s.revoked:
            return None
        exp = s.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            return None
        return {"token": s.token, "user_id": s.user_id, "expires_at": s.expires_at.isoformat(), "revoked": s.revoked}


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from scrapyard.database.base_model import Base

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        engine = create_engine(f"sqlite:///{os.path.join(tmp, 't.db')}")
        Base.metadata.create_all(engine)
        try:
            with DbSession(engine) as db:
                mgr = SessionManager(db, ttl_hours=24)

                # create + lookup
                tok = mgr.create(7)
                assert mgr.user_id_for(tok) == 7, "fresh session must resolve its user"

                # negative: an unknown token resolves to nobody
                assert mgr.user_id_for("bogus-token") is None, "unknown token denied"

                # revoke -> lookup denied
                assert mgr.revoke(tok) is True
                assert mgr.user_id_for(tok) is None, "revoked session must be denied"

                # expired session is denied (freeze by writing a past expiry)
                exp_tok = mgr.create(9)
                s = db.scalars(select(Session).where(Session.token == exp_tok)).first()
                s.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
                db.flush()
                assert mgr.user_id_for(exp_tok) is None, "expired session must be denied"

                # negative: a past expiry on create is rejected
                try:
                    mgr.create_with_expiry(1, datetime.now(timezone.utc) - timedelta(minutes=5))
                    raise AssertionError("past expiry must raise InvalidExpiryTimeError")
                except InvalidExpiryTimeError:
                    pass

                # negative: revoking a nonexistent session raises
                try:
                    mgr.revoke("never-existed")
                    raise AssertionError("revoking unknown token must raise")
                except SessionNotFoundError:
                    pass
                db.commit()
        finally:
            engine.dispose()
    print("session_manager self-test passed")


if __name__ == "__main__":
    _selftest()
