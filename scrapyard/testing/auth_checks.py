"""
auth_checks — Verify login/refresh/permission paths.

### PART-META-JSON
{
  "name": "auth_checks",
  "layer": "testing",
  "purpose": "Verify login/refresh/permission paths.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: check_auth_roundtrip(db).",
  "outputs": "Returns: check_auth_roundtrip -> dict.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `check_auth_roundtrip` from `scrapyard.testing.auth_checks` and call it as shown in `example`; run `py -m scrapyard.testing.auth_checks` to see its offline selftest.",
  "example": "from scrapyard.testing.auth_checks import check_auth_roundtrip",
  "import_path": "scrapyard.testing.auth_checks"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

def check_auth_roundtrip(db) -> dict:
    """Verify register->authenticate works and rejects a wrong password."""
    from scrapyard.identity.users import UserService
    svc = UserService(db)
    u = svc.create("authcheck@example.test", "password123"); db.flush()
    return {"ok": svc.authenticate("authcheck@example.test", "password123") is not None
            and svc.authenticate("authcheck@example.test", "wrong") is None}


def _selftest() -> None:
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import IntPKModel
    import scrapyard.identity.users as users_mod  # registers the User table

    # PASS fixture: a real, correct UserService over in-memory sqlite.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        engine = create_engine(f"sqlite:///{os.path.join(d, 't.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                res = check_auth_roundtrip(db)
                assert res == {"ok": True}, res
                db.rollback()
        finally:
            engine.dispose()

    # FAIL fixture: a broken UserService whose authenticate() accepts ANY
    # password. The check must catch that the wrong-password path is not
    # rejected and report ok=False.
    class _BrokenService:
        def __init__(self, db):
            pass

        def create(self, email, password):
            class _U:
                id = 1
            return _U()

        def authenticate(self, email, password):
            return object()  # always "succeeds", even for the wrong password

    class _FakeDB:
        def flush(self):
            pass

    original = users_mod.UserService
    users_mod.UserService = _BrokenService
    try:
        res = check_auth_roundtrip(_FakeDB())
        assert res == {"ok": False}, res  # check correctly reports the failure
    finally:
        users_mod.UserService = original

    print("auth_checks selftest OK")


if __name__ == "__main__":
    _selftest()
