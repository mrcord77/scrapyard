"""
user_management — Search/suspend/restore/edit users (admin).

### PART-META-JSON
{
  "name": "user_management",
  "layer": "admin",
  "purpose": "Search/suspend/restore/edit users (admin).",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: search_users(db, *, filters, limit, offset, active_only, sort, order); update_user_status(db, user_id, status, *, actor_user_id, reason, audit); bulk_update_user_status(db, user_ids, status, *, actor_user_id, reason, audit); get_user_by_id(db, user_id); update_user(db, user_id, data, *, actor_user_id, audit); UserStatusUpdate(...) (plus more).",
  "outputs": "Returns: search_users -> List[User]; update_user_status -> Optional[User]; bulk_update_user_status -> List[User]; get_user_by_id -> Optional[User]; update_user -> Optional[User].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `search_users` from `scrapyard.admin.user_management` and call it as shown in `example`; run `py -m scrapyard.admin.user_management` to see its offline selftest.",
  "example": "from scrapyard.admin.user_management import search_users",
  "import_path": "scrapyard.admin.user_management"
}
### END-PART-META
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, Mapped, mapped_column
from sqlalchemy import select, delete, update, and_, or_, func
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException
from pydantic import BaseModel
from scrapyard.identity.users import User
from scrapyard.admin.audit_logs import record


class UserStatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = None

def search_users(db: Session, *, filters: dict = None, limit: int = 50, offset: int = 0, active_only: bool = False, sort: str = None, order: str = "asc") -> List[User]:
    q = select(User)
    if active_only:
        q = q.where(User.is_active == True)
    if filters:
        for key, value in filters.items():
            q = q.where(getattr(User, key) == value)
    if sort and order.lower() in ["asc", "desc"]:
        column_to_sort = getattr(User, sort)
        q = q.order_by(column_to_sort.asc() if order.lower() == "asc" else column_to_sort.desc())
    return list(db.scalars(q.limit(limit).offset(offset)))

def update_user_status(db: Session, user_id: int, status: str, *, actor_user_id: int = None, reason: Optional[str] = None, audit: bool = True) -> Optional[User]:
    from scrapyard.identity.users import User
    u = db.get(User, user_id)
    if not u:
        return None
    status_l = status.lower()
    if status_l in ("active", "restored", "suspended", "locked"):
        # 'active'/'restored' reactivate; 'suspended'/'locked' deactivate.
        u.is_active = status_l in ("active", "restored")
        record(db, action="user_update_status", actor_user_id=actor_user_id, target=f"user:{user_id}", detail=f"Status: {status}, Reason: {reason}")
    else:
        raise HTTPException(status_code=400, detail="Invalid status value")
    db.flush()
    return u

def bulk_update_user_status(db: Session, user_ids: List[int], status: str, *, actor_user_id: int = None, reason: Optional[str] = None, audit: bool = True) -> List[User]:
    from scrapyard.identity.users import User
    q = select(User).where(User.id.in_(user_ids))
    users = db.scalars(q)
    status_l = status.lower()
    if status_l not in ("active", "restored", "suspended", "locked"):
        raise HTTPException(status_code=400, detail="Invalid status value")
    updated_users = []
    for u in users:
        u.is_active = status_l in ("active", "restored")
        record(db, action="bulk_user_update_status", actor_user_id=actor_user_id, target=f"user:{u.id}", detail=f"Status: {status}, Reason: {reason}")
        db.flush()
        updated_users.append(u)
    return updated_users

def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    from scrapyard.identity.users import User
    u = db.get(User, user_id)
    return u

def update_user(db: Session, user_id: int, data: Dict[str, Any], *, actor_user_id: int = None, audit: bool = True) -> Optional[User]:
    from scrapyard.identity.users import User
    u = db.get(User, user_id)
    if not u:
        return None
    for key, value in data.items():
        setattr(u, key, value)
    record(db, action="user_update", actor_user_id=actor_user_id, target=f"user:{u.id}", detail=str(data))
    db.flush()
    return u

def delete_user(db: Session, user_id: int, *, actor_user_id: int = None, audit: bool = True) -> Optional[User]:
    from scrapyard.identity.users import User
    u = db.get(User, user_id)
    if not u:
        return None
    record(db, action="user_delete", actor_user_id=actor_user_id, target=f"user:{u.id}", detail=str(u))
    db.delete(u)
    db.flush()
    return u

def audit_log_user_action(db: Session, action: str, user_id: int, actor_user_id: int, detail: str) -> None:
    record(db, action=action, actor_user_id=actor_user_id, target=f"user:{user_id}", detail=detail)

def serialize_user(user: User, include_secrets: bool = False) -> Dict[str, Any]:
    """Serialize a user row to a dict; secret fields are excluded by default.

    Never mutates the ORM instance (the previous version deleted keys from
    user.__dict__ and crashed on the nonexistent 'password' key).
    """
    secret_fields = {"password", "password_hash", "token"}
    out = {}
    for c in user.__table__.columns:
        if not include_secrets and c.name in secret_fields:
            continue
        out[c.name] = getattr(user, c.name)
    return out


# --- grafted from original part (API stability) ---
def list_users(db, *, limit=50, offset=0, active_only=False):
    q = select(User)
    if active_only:
        q = q.where(User.is_active == True)
    return list(db.scalars(q.limit(limit).offset(offset)))

def set_active(db, user_id, active, *, actor_user_id=None):
    u = db.get(User, user_id)
    if not u:
        return None
    u.is_active = active
    record(db, action="user_set_active", actor_user_id=actor_user_id, target=f"user:{user_id}", detail=str(active))
    db.flush()
    return u

def user_count(db):
    return db.scalar(select(func.count()).select_from(User)) or 0


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from scrapyard.database.base_model import Base
    import scrapyard.admin.audit_logs  # noqa: F401

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                a = User(email="a@example.com", password_hash="h1", role="admin")
                b = User(email="b@example.com", password_hash="h2")
                db.add_all([a, b]); db.commit()

                # search / list / count
                assert {u.email for u in search_users(db)} == {"a@example.com", "b@example.com"}
                assert [u.email for u in search_users(db, filters={"role": "admin"})] == ["a@example.com"]
                assert user_count(db) == 2
                assert get_user_by_id(db, a.id).email == "a@example.com"
                assert get_user_by_id(db, 9999) is None

                # status semantics: suspended deactivates, restored reactivates
                u = update_user_status(db, b.id, "suspended", actor_user_id=a.id)
                assert u.is_active is False
                u = update_user_status(db, b.id, "restored", actor_user_id=a.id)
                assert u.is_active is True, "restored must reactivate"
                try:
                    update_user_status(db, b.id, "banana", actor_user_id=a.id)
                    raise AssertionError("invalid status must 400")
                except HTTPException as e:
                    assert e.status_code == 400
                assert update_user_status(db, 9999, "suspended") is None

                # bulk status
                out = bulk_update_user_status(db, [a.id, b.id], "locked", actor_user_id=a.id)
                assert len(out) == 2 and all(not u.is_active for u in out)
                bulk_update_user_status(db, [a.id, b.id], "active", actor_user_id=a.id)

                # serialize: excludes secrets by default, does not mutate the row
                s = serialize_user(a)
                assert "password_hash" not in s and s["email"] == "a@example.com"
                assert a.password_hash == "h1", "serialize_user must not mutate the ORM row"
                assert serialize_user(a, include_secrets=True)["password_hash"] == "h1"

                # update + delete audited
                update_user(db, b.id, {"role": "support"}, actor_user_id=a.id)
                assert get_user_by_id(db, b.id).role == "support"
                assert delete_user(db, b.id, actor_user_id=a.id) is not None
                db.commit()
                assert get_user_by_id(db, b.id) is None
                assert delete_user(db, b.id) is None
                assert user_count(db) == 1
        finally:
            engine.dispose()
    print("user_management self-test passed")


if __name__ == "__main__":
    _selftest()
