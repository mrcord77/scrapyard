"""
impersonation — Authorized, logged user impersonation for support.

### PART-META-JSON
{
  "name": "impersonation",
  "layer": "admin",
  "purpose": "User impersonation for support staff, gated by a required authorizer check and always written to the tamper-evident admin audit log. start_impersonation refuses (PermissionError) unless the injected authorizer confirms the admin is privileged - fail closed.",
  "addition": true,
  "status": "core",
  "dependencies": ["scrapyard.admin.audit_logs", "scrapyard.identity.users (default authorizer)"],
  "inputs": "SQLAlchemy Session, admin_user_id, target_user_id, optional is_authorized callable (admin_user_id -> bool).",
  "outputs": "Impersonation marker dict {impersonator, acting_as}; PermissionError when authorization is absent or fails; audited start/stop entries.",
  "files_created": [],
  "security_notes": "FAIL CLOSED: without a passing authorization check no impersonation marker is issued. The check is pluggable - pass is_authorized (e.g. a roles lookup) or rely on the default, which loads the admin's User row and requires role == 'admin' AND is_active; a missing user, missing role model, or authorizer exception all DENY. Self-impersonation is refused. The returned marker is only as strong as the auth layer that carries it: bind it to the admin's session server-side, never hand it to the client unsigned. Every start/stop is recorded in the hash-chained audit log BEFORE the marker is returned.",
  "ai_usage": "Call start_impersonation(db, admin_id, target_id, is_authorized=your_gate) inside an authenticated admin context; carry the returned marker as the effective identity; call stop_impersonation when done.",
  "example": "from scrapyard.admin.impersonation import start_impersonation, stop_impersonation",
  "import_path": "scrapyard.admin.impersonation"
}
### END-PART-META
"""
from __future__ import annotations

from typing import Callable, Optional

STATUS = "core"


def _default_authorizer(db) -> Callable[[int], bool]:
    """Default privilege gate: the admin's User row must exist, be active,
    and carry role == 'admin'. Any lookup failure denies (fail closed)."""

    def _check(admin_user_id: int) -> bool:
        try:
            from scrapyard.identity.users import User
            user = db.get(User, admin_user_id)
            return bool(user is not None and user.is_active and user.role == "admin")
        except Exception:
            return False

    return _check


def start_impersonation(db, admin_user_id: int, target_user_id: int,
                        *, is_authorized: Optional[Callable[[int], bool]] = None) -> dict:
    """Begin an impersonation session - authorized and audited.

    Args:
        db: SQLAlchemy session.
        admin_user_id: The acting administrator.
        target_user_id: The user to impersonate.
        is_authorized: Privilege gate ``(admin_user_id) -> bool``. When omitted,
            the default gate requires an active User row with role == 'admin'.

    Returns:
        A marker the auth layer carries as the effective identity.

    Raises:
        PermissionError: If the authorization check is absent, fails, or raises
            (fail closed), or on attempted self-impersonation.
    """
    from scrapyard.admin.audit_logs import record

    if admin_user_id == target_user_id:
        raise PermissionError("self-impersonation is not permitted")

    gate = is_authorized if is_authorized is not None else _default_authorizer(db)
    try:
        allowed = bool(gate(admin_user_id))
    except Exception as exc:  # fail closed on authorizer faults
        record(db, action="impersonation_denied", actor_user_id=admin_user_id,
               target=f"user:{target_user_id}", detail=f"authorizer error: {type(exc).__name__}")
        db.flush()
        raise PermissionError("impersonation authorizer failed") from exc

    if not allowed:
        record(db, action="impersonation_denied", actor_user_id=admin_user_id,
               target=f"user:{target_user_id}", detail="admin is not privileged")
        db.flush()
        raise PermissionError(
            f"user {admin_user_id} is not authorized to impersonate user {target_user_id}")

    record(db, action="impersonation_start", actor_user_id=admin_user_id,
           target=f"user:{target_user_id}", detail="admin impersonation began")
    db.flush()
    return {"impersonator": admin_user_id, "acting_as": target_user_id}


def stop_impersonation(db, admin_user_id: int, target_user_id: int) -> dict:
    from scrapyard.admin.audit_logs import record
    record(db, action="impersonation_stop", actor_user_id=admin_user_id,
           target=f"user:{target_user_id}")
    db.flush()
    return {"ended": True}


def _selftest() -> None:
    """Offline self-test: the gate must fail closed and audit every outcome."""
    import os
    import tempfile
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from scrapyard.database.base_model import Base
    from scrapyard.identity.users import User
    import scrapyard.admin.audit_logs  # noqa: F401 - register audit table
    from scrapyard.admin.audit_logs import AuditLog

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                admin = User(email="admin@example.com", password_hash="x", role="admin")
                support = User(email="support@example.com", password_hash="x", role="support")
                target = User(email="member@example.com", password_hash="x")
                db.add_all([admin, support, target])
                db.commit()

                # Default gate: role == 'admin' passes.
                marker = start_impersonation(db, admin.id, target.id)
                assert marker == {"impersonator": admin.id, "acting_as": target.id}
                assert stop_impersonation(db, admin.id, target.id) == {"ended": True}

                # Default gate: non-admin denied, no marker.
                try:
                    start_impersonation(db, support.id, target.id)
                    raise AssertionError("non-admin impersonation must be denied")
                except PermissionError:
                    pass

                # Missing admin user denied (fail closed).
                try:
                    start_impersonation(db, 999999, target.id)
                    raise AssertionError("unknown admin must be denied")
                except PermissionError:
                    pass

                # Custom authorizer honored both ways.
                marker = start_impersonation(db, support.id, target.id,
                                             is_authorized=lambda uid: uid == support.id)
                assert marker["impersonator"] == support.id
                try:
                    start_impersonation(db, admin.id, target.id,
                                        is_authorized=lambda uid: False)
                    raise AssertionError("false authorizer must deny")
                except PermissionError:
                    pass

                # Raising authorizer denies (fail closed), never leaks a marker.
                def _boom(uid):
                    raise RuntimeError("authz backend down")
                try:
                    start_impersonation(db, admin.id, target.id, is_authorized=_boom)
                    raise AssertionError("raising authorizer must deny")
                except PermissionError:
                    pass

                # Self-impersonation refused.
                try:
                    start_impersonation(db, admin.id, admin.id)
                    raise AssertionError("self-impersonation must be denied")
                except PermissionError:
                    pass

                # Every outcome audited: starts, stops, denials.
                actions = [a.action for a in db.scalars(select(AuditLog))]
                assert actions.count("impersonation_start") == 2
                assert actions.count("impersonation_stop") == 1
                assert actions.count("impersonation_denied") >= 4
        finally:
            engine.dispose()

    print("impersonation self-test passed")


if __name__ == "__main__":
    _selftest()
