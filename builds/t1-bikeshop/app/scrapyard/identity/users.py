"""
users — User model + core user service (create/find/update).

### PART-META-JSON
{
  "name": "users",
  "layer": "identity",
  "purpose": "User model + core user service (create/find/update).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: UserNotFoundError(...); User(...); UserCreate(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `UserNotFoundError` from `scrapyard.identity.users` and call it as shown in `example`; run `py -m scrapyard.identity.users` to see its offline selftest.",
  "example": "from scrapyard.identity.users import UserNotFoundError",
  "import_path": "scrapyard.identity.users"
}
### END-PART-META
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar

from sqlalchemy import Boolean, DateTime, String, func, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel
from scrapyard.identity.password_hashing import (
    hash_password,
    needs_rehash,
    verify_password,
)
from scrapyard.security.password_policy import enforce

STATUS = "core"

log = logging.getLogger("scrapyard.identity.users")

T = TypeVar("T")


class UserNotFoundError(Exception):
    """Raised when a user lookup by id/email finds nothing."""


class User(IntPKModel):
    __tablename__ = "users_users"
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


@dataclass
class UserCreate:
    email: str
    password: str
    role: Optional[str] = None


@dataclass
class UserUpdate:
    """Sparse update payload; None means 'leave unchanged'."""
    email: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[str] = None

    def changes(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.email is not None:
            out["email"] = self.email.lower().strip()
        if self.password is not None:
            enforce(self.password)
            out["password_hash"] = hash_password(self.password)
        if self.is_active is not None:
            out["is_active"] = self.is_active
        if self.role is not None:
            out["role"] = self.role
        return out


@dataclass
class Page(Generic[T]):
    items: List[T]
    total: int

    def to_dict(self) -> Dict[str, Any]:
        return {"items": self.items, "total": self.total}


class UserService:
    def __init__(self, db: Session):
        self.db = db

    # -- original core API (kept stable) ------------------------------------
    def create(self, email: str, password: str) -> User:
        return self.create_user(UserCreate(email=email, password=password))

    def get(self, user_id: int) -> Optional[User]:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> Optional[User]:
        stmt = select(User).where(User.email == email.lower().strip())
        return self.db.scalars(stmt).first()

    def authenticate(self, email: str, password: str) -> Optional[User]:
        u = self.get_by_email(email)
        if not u or not u.is_active:
            return None
        if not verify_password(password, u.password_hash):
            return None
        if needs_rehash(u.password_hash):
            u.password_hash = hash_password(password)
            self.db.flush()
        return u

    def deactivate(self, user_id: int) -> Optional[User]:
        u = self.db.get(User, user_id)
        if not u:
            return None
        u.is_active = False
        self.db.flush()
        return u

    # -- extended service API ------------------------------------------------
    def create_user(self, user_data: UserCreate) -> User:
        enforce(user_data.password)
        u = User(
            email=user_data.email.lower().strip(),
            password_hash=hash_password(user_data.password),
            role=user_data.role,
        )
        self.db.add(u)
        self.db.flush()
        self.audit_log("user.created", u, {})
        return u

    def bulk_create_users(self, users_data: List[UserCreate]) -> List[User]:
        return [self.create_user(d) for d in users_data]

    def find_users(
        self,
        email: Optional[str] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[User]:
        stmt = select(User)
        if email:
            stmt = stmt.where(User.email == email.lower().strip())
        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)
        total = self.db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0
        rows = list(
            self.db.scalars(
                stmt.order_by(User.id).offset((page - 1) * size).limit(size)
            )
        )
        return Page(items=rows, total=total)

    def search_users(self, query: str, page: int = 1, size: int = 20) -> Page[User]:
        like = f"%{query.lower().strip()}%"
        stmt = select(User).where(
            or_(User.email.ilike(like), User.role.ilike(like))
        )
        total = self.db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0
        rows = list(
            self.db.scalars(
                stmt.order_by(User.id).offset((page - 1) * size).limit(size)
            )
        )
        return Page(items=rows, total=total)

    def update_user(self, user_id: int, user_data: UserUpdate) -> User:
        u = self.db.get(User, user_id)
        if not u:
            raise UserNotFoundError(f"user {user_id} not found")
        for field, value in user_data.changes().items():
            setattr(u, field, value)
        self.db.flush()
        self.audit_log("user.updated", u, {"fields": sorted(user_data.changes())})
        return u

    def deactivate_user(self, user_id: int) -> User:
        u = self.deactivate(user_id)
        if not u:
            raise UserNotFoundError(f"user {user_id} not found")
        self.audit_log("user.deactivated", u, {})
        return u

    def archive_user(self, user_id: int) -> User:
        return self.deactivate_user(user_id)

    def user_exists(self, email: str) -> bool:
        return self.get_by_email(email) is not None

    def get_user_roles(self, user_id: int) -> List[str]:
        u = self.db.get(User, user_id)
        if not u:
            raise UserNotFoundError(f"user {user_id} not found")
        return [u.role] if u.role else []

    def apply_password_policy(self, password: str) -> bool:
        enforce(password)
        return True

    def serialize_user(self, user: User) -> dict:
        return {
            "id": user.id,
            "email": user.email,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "roles": [user.role] if user.role else [],
        }

    def audit_log(self, event_type: str, user: User, details: Dict[str, Any]) -> None:
        """Structured audit line; never logs credentials or PII beyond the id."""
        log.info("audit %s user_id=%s %s", event_type, user.id, details)


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.exc import IntegrityError
    from scrapyard.database.base_model import Base
    from scrapyard.security.password_policy import PolicyError

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        engine = create_engine(f"sqlite:///{os.path.join(tmp, 't.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                svc = UserService(db)

                # create + fetch
                u = svc.create("Alice@Example.com", "Sup3rSecret!")
                assert u.id and u.email == "alice@example.com", "email is normalised"
                assert svc.get(u.id).id == u.id, "get by id must round-trip"
                assert svc.get_by_email("alice@example.com").id == u.id

                # authenticate: correct password succeeds, wrong password fails
                assert svc.authenticate("alice@example.com", "Sup3rSecret!") is not None
                assert svc.authenticate("alice@example.com", "wrong-pass!") is None, \
                    "wrong password must be rejected"

                # negative: a weak password is rejected by policy
                try:
                    svc.create("weak@example.com", "short")
                    raise AssertionError("weak password must raise PolicyError")
                except PolicyError:
                    pass

                # negative: duplicate email violates the unique constraint
                try:
                    svc.create("alice@example.com", "An0therStrong!")
                    db.flush()
                    raise AssertionError("duplicate email must raise IntegrityError")
                except IntegrityError:
                    db.rollback()
        finally:
            engine.dispose()
    print("users self-test passed")


if __name__ == "__main__":
    _selftest()
