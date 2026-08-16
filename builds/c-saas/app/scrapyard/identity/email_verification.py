"""
email_verification — Email confirmation token issue + verify.

### PART-META-JSON
{
  "name": "email_verification",
  "layer": "identity",
  "purpose": "Email confirmation token issue + verify.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: issue(db, user_id); verify(db, token); EmailVerification(...).",
  "outputs": "Returns: issue -> str; verify -> bool.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `issue` from `scrapyard.identity.email_verification` and call it as shown in `example`; run `py -m scrapyard.identity.email_verification` to see its offline selftest.",
  "example": "from scrapyard.identity.email_verification import issue",
  "import_path": "scrapyard.identity.email_verification"
}
### END-PART-META
"""
from __future__ import annotations
import secrets as _secrets
STATUS = "core"
from sqlalchemy import String, Integer, Boolean, select
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel

class EmailVerification(IntPKModel):
    __tablename__ = "email_verifications"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False)

def issue(db, user_id: int) -> str:
    tok = _secrets.token_urlsafe(24)
    db.add(EmailVerification(user_id=user_id, token=tok)); db.flush(); return tok

def verify(db, token: str) -> bool:
    from scrapyard.identity.users import User
    row = db.scalars(select(EmailVerification).where(EmailVerification.token == token)).first()
    if not row or row.used:
        return False
    user = db.get(User, row.user_id)
    if not user:
        return False
    user.is_verified = True; row.used = True; db.flush(); return True


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import Base
    from scrapyard.identity.users import User
    from scrapyard.identity.password_hashing import hash_password

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        engine = create_engine(f"sqlite:///{os.path.join(tmp, 't.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                u = User(email="v@example.com",
                         password_hash=hash_password("Passw0rd!ok"))
                db.add(u); db.flush()
                assert not u.is_verified, "user starts unverified"
                tok = issue(db, u.id)
                assert isinstance(tok, str) and tok, "issue must return a token"
                # valid token verifies and flips the flag
                assert verify(db, tok) is True, "valid token must verify"
                assert u.is_verified is True, "verify must set is_verified"
                # negative: a consumed token cannot be reused
                assert verify(db, tok) is False, "used token must be rejected"
                # negative: an unknown/tampered token is rejected
                assert verify(db, tok + "tampered") is False, "bad token must be rejected"
                db.commit()
        finally:
            engine.dispose()
    print("email_verification self-test passed")


if __name__ == "__main__":
    _selftest()
