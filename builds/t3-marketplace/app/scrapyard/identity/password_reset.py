"""
password_reset — Token-based password reset request + confirm flow.

### PART-META-JSON
{
  "name": "password_reset",
  "layer": "identity",
  "purpose": "Token-based password reset request + confirm flow.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: generate_reset_token(db, user_id, ttl_min, token_length); get_reset_token(db, token); consume_reset_token(db, token, new_password, policy); delete_expired_tokens(db, cutoff); bulk_request_resets(db, user_ids, ttl_min); TokenAlreadyUsedError(...); TokenExpiredError(...); PasswordResetToken(...) (plus more).",
  "outputs": "Returns: generate_reset_token -> str; get_reset_token -> Optional[PasswordResetToken]; consume_reset_token -> bool; delete_expired_tokens -> int; bulk_request_resets -> List[str].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `generate_reset_token` from `scrapyard.identity.password_reset` and call it as shown in `example`; run `py -m scrapyard.identity.password_reset` to see its offline selftest.",
  "example": "from scrapyard.identity.password_reset import generate_reset_token",
  "import_path": "scrapyard.identity.password_reset"
}
### END-PART-META
"""
from __future__ import annotations
import secrets as _secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import Boolean, DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from sqlalchemy.exc import NoResultFound
from scrapyard.database.base_model import IntPKModel
from scrapyard.identity.users import User
from scrapyard.identity.password_hashing import hash_password
from scrapyard.security.password_policy import enforce

STATUS = "core"

class TokenAlreadyUsedError(Exception):
    pass

class TokenExpiredError(Exception):
    pass

class PasswordResetToken(IntPKModel):
    __tablename__ = "password_reset_tokens"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)

def generate_reset_token(db: Session, user_id: int, ttl_min: int = 30, token_length: int = 32) -> str:
    tok = _secrets.token_urlsafe(token_length)
    db.add(PasswordResetToken(user_id=user_id, token=tok,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_min)))
    db.flush()
    return tok

def get_reset_token(db: Session, token: str) -> Optional[PasswordResetToken]:
    try:
        return db.scalars(select(PasswordResetToken).where(PasswordResetToken.token == token)).one()
    except NoResultFound:
        return None

def consume_reset_token(db: Session, token: str, new_password: str, policy: Optional[Any] = None) -> bool:
    row = get_reset_token(db, token)
    if not row or row.used:
        raise TokenAlreadyUsedError("Token already used")
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        raise TokenExpiredError("Token expired")

    # NOTE: password_policy.enforce is (password, *, min_len); passing `policy`
    # positionally raised TypeError on every call (the whole consume path was
    # dead). A custom `policy` object is not consumable by enforce(), so honour
    # the default policy — matching the sibling confirm_reset() below.
    enforce(new_password)
    user = db.get(User, row.user_id)
    if not user:
        return False
    user.password_hash = hash_password(new_password)
    row.used = True
    db.flush()
    return True

def delete_expired_tokens(db: Session, cutoff: Optional[datetime] = None) -> int:
    query = select(PasswordResetToken).where(
        (PasswordResetToken.expires_at < datetime.now(timezone.utc)) |
        (PasswordResetToken.used == True)
    )
    if cutoff is not None:
        query = query.where(PasswordResetToken.expires_at <= cutoff)

    rows = db.scalars(query).all()
    count = len(rows)
    for row in rows:
        db.delete(row)
    db.commit()
    return count

def bulk_request_resets(db: Session, user_ids: List[int], ttl_min: int = 30) -> List[str]:
    with db.begin():
        tokens = []
        for user_id in user_ids:
            token = generate_reset_token(db, user_id, ttl_min)
            tokens.append(token)
    return tokens

def reset_token_serializer(token: PasswordResetToken) -> Dict[str, Any]:
    return {
        "token": token.token,
        "user_id": token.user_id,
        "expires_at": token.expires_at.isoformat(),
        "used": token.used
    }

def reset_token_deserializer(data: Dict[str, Any]) -> PasswordResetToken:
    return PasswordResetToken(**data)

def validate_token_for_user(db: Session, token: str, user_id: int) -> bool:
    row = get_reset_token(db, token)
    if not row or row.user_id != user_id:
        return False
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        raise TokenExpiredError("Token expired")
    return True

def get_user_reset_tokens(db: Session, user_id: int, limit: int = 20, offset: int = 0) -> List[PasswordResetToken]:
    query = select(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
    tokens = db.scalars(query.offset(offset).limit(limit)).all()
    return tokens


# --- grafted from original part (API stability) ---
def request_reset(db, user_id: int, ttl_min: int = 30) -> str:
    tok = _secrets.token_urlsafe(32)
    db.add(PasswordResetToken(user_id=user_id, token=tok,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_min)))
    db.flush(); return tok

def confirm_reset(db, token: str, new_password: str) -> bool:
    from scrapyard.identity.users import User
    from scrapyard.identity.password_hashing import hash_password
    from scrapyard.security.password_policy import enforce
    row = db.scalars(select(PasswordResetToken).where(PasswordResetToken.token == token)).first()
    if not row or row.used:
        return False
    exp = row.expires_at
    if exp.tzinfo is None: exp = exp.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        return False
    enforce(new_password)
    user = db.get(User, row.user_id)
    if not user:
        return False
    user.password_hash = hash_password(new_password); row.used = True; db.flush()
    return True


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import Base
    from scrapyard.identity.password_hashing import verify_password

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        engine = create_engine(f"sqlite:///{os.path.join(tmp, 't.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                u = User(email="r@example.com",
                         password_hash=hash_password("OldPassw0rd!"))
                db.add(u); db.flush()

                new_pw = "BrandNewP4ss!"
                tok = generate_reset_token(db, u.id, ttl_min=30)
                # happy path: valid token consumes and rotates the password hash
                assert consume_reset_token(db, tok, new_pw) is True
                assert verify_password(new_pw, u.password_hash), "password must rotate"

                # negative: a consumed token cannot be replayed
                try:
                    consume_reset_token(db, tok, new_pw)
                    raise AssertionError("reused token must raise")
                except TokenAlreadyUsedError:
                    pass

                # negative: an expired token is rejected
                exp_tok = generate_reset_token(db, u.id, ttl_min=30)
                row = get_reset_token(db, exp_tok)
                row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
                db.flush()
                try:
                    consume_reset_token(db, exp_tok, new_pw)
                    raise AssertionError("expired token must raise")
                except TokenExpiredError:
                    pass

                # negative: an unknown/tampered token is rejected
                try:
                    consume_reset_token(db, "not-a-real-token", new_pw)
                    raise AssertionError("unknown token must raise")
                except TokenAlreadyUsedError:
                    pass

                # validate_token_for_user: right user ok, wrong user rejected
                live = generate_reset_token(db, u.id, ttl_min=30)
                assert validate_token_for_user(db, live, u.id) is True
                assert validate_token_for_user(db, live, u.id + 999) is False
                db.commit()
        finally:
            engine.dispose()
    print("password_reset self-test passed")


if __name__ == "__main__":
    _selftest()
