"""
roles — Role definitions + assignment to principals.

### PART-META-JSON
{
  "name": "roles",
  "layer": "authorization",
  "purpose": "Role definitions + assignment to principals.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: permissions_for(role); role_allows(role, permission); grant(db, user_id, role); revoke(db, user_id, role); roles_for(db, user_id); UserRole(...); Principal(...) (plus more).",
  "outputs": "Returns: permissions_for -> list[str]; role_allows -> bool; grant -> None; revoke -> None; roles_for -> set.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `permissions_for` from `scrapyard.authorization.roles` and call it as shown in `example`; run `py -m scrapyard.authorization.roles` to see its offline selftest.",
  "example": "from scrapyard.authorization.roles import permissions_for",
  "import_path": "scrapyard.authorization.roles"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
ROLE_PERMISSIONS={
    "owner":["*"],
    "admin":["users:*","content:*","billing:read","audit:read"],
    "member":["content:read","content:write","profile:*"],
    "viewer":["content:read"],
}
def permissions_for(role: str) -> list[str]:
    return list(ROLE_PERMISSIONS.get(role, []))
def role_allows(role: str, permission: str) -> bool:
    from scrapyard.authorization.permissions import has_permission
    from types import SimpleNamespace
    return has_permission(SimpleNamespace(permissions=permissions_for(role)), permission)


# --- persistent user->role assignment (the storage the definitions above lacked) ---
from dataclasses import dataclass, field
from sqlalchemy import String, Integer, UniqueConstraint, select, delete
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel


class UserRole(IntPKModel):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_user_role"),)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(50), index=True)


@dataclass
class Principal:
    """Authenticated subject with permissions expanded from assigned roles —
    consumable by scrapyard.authorization.permissions.has_permission / require()."""
    user_id: int
    roles: set = field(default_factory=set)
    permissions: set = field(default_factory=set)


def grant(db, user_id: int, role: str) -> None:
    """Idempotently assign a role to a user. Trusted path only (seed/ops/admin)."""
    if not db.scalar(select(UserRole).where(UserRole.user_id == user_id, UserRole.role == role)):
        db.add(UserRole(user_id=user_id, role=role)); db.flush()


def revoke(db, user_id: int, role: str) -> None:
    db.execute(delete(UserRole).where(UserRole.user_id == user_id, UserRole.role == role)); db.flush()


def roles_for(db, user_id: int) -> set:
    return set(db.scalars(select(UserRole.role).where(UserRole.user_id == user_id)).all())


def principal_for(db, user_id: int) -> Principal:
    roles = roles_for(db, user_id)
    perms: set = set()
    for r in roles:
        perms |= set(permissions_for(r))
    return Principal(user_id=user_id, roles=roles, permissions=perms)


def has_role(db, user_id: int, role: str) -> bool:
    """True if the user holds the role, or holds any role that grants '*' (superuser)."""
    held = roles_for(db, user_id)
    if role in held:
        return True
    return any("*" in ROLE_PERMISSIONS.get(r, []) for r in held)


def _selftest() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from scrapyard.database.base_model import Base
    from scrapyard.authorization.permissions import configure_permission_policy

    configure_permission_policy("wildcard")
    assert permissions_for("owner") == ["*"]
    assert role_allows("admin", "users:read") is True     # admin has users:*
    assert role_allows("viewer", "content:write") is False    # negative: viewer is read-only
    assert role_allows("nobody", "content:read") is False     # negative: unknown role -> no perms

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    grant(db, 1, "admin")
    grant(db, 1, "admin")                                 # idempotent (unique constraint honoured)
    assert roles_for(db, 1) == {"admin"}
    assert has_role(db, 1, "admin") is True
    assert has_role(db, 1, "owner") is False              # admin does not imply owner
    assert principal_for(db, 1).permissions == set(permissions_for("admin"))
    grant(db, 1, "owner")
    assert has_role(db, 1, "anything") is True            # owner holds '*' -> superuser
    revoke(db, 1, "owner")
    assert has_role(db, 1, "anything") is False           # revoked -> superuser gone
    db.close()
    print("roles selftest: PASS")


if __name__ == "__main__":
    _selftest()
