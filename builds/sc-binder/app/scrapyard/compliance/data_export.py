"""
data_export — Export a user's data (DSAR/portability).

### PART-META-JSON
{
  "name": "data_export",
  "layer": "compliance",
  "purpose": "Export a user's data (DSAR/portability).",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: export_user_data(db, user_id).",
  "outputs": "Returns: export_user_data -> dict.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `export_user_data` from `scrapyard.compliance.data_export` and call it as shown in `example`; run `py -m scrapyard.compliance.data_export` to see its offline selftest.",
  "example": "from scrapyard.compliance.data_export import export_user_data",
  "import_path": "scrapyard.compliance.data_export"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
from sqlalchemy import inspect, select

# Credential/secret columns are REDACTED from exports: a DSAR export describes the
# data held about a user; shipping a live session token (account takeover from a
# leaked export file) or a password hash (offline cracking target) is a vuln,
# not portability. (Found 2026-08-16: export contained both, verbatim.)
SECRET_COLUMNS = {"password_hash", "token", "secret", "api_key", "private_key"}
_REDACTED = "[REDACTED-CREDENTIAL]"

def export_user_data(db, user_id: int) -> dict:
    """Collect everything stored about a user (DSAR / data portability). Returns a
    JSON-serializable dict keyed by table name. Credential columns are redacted."""
    from scrapyard.identity.users import User
    out = {}
    user = db.get(User, user_id)
    if user is None:
        return {"error": "not found"}
    def row_to_dict(obj):
        return {c.key: (_REDACTED if c.key in SECRET_COLUMNS else _ser(getattr(obj, c.key)))
                for c in inspect(type(obj)).columns}
    out["users"] = [row_to_dict(user)]
    for mapper in User.registry.mappers:
        model = mapper.class_
        cols = {c.key for c in inspect(model).columns}
        if model is User or "user_id" not in cols:
            continue
        rows = db.scalars(select(model).where(model.user_id == user_id)).all()
        if rows:
            out[model.__tablename__] = [row_to_dict(r) for r in rows]
    return out

def _ser(v):
    from datetime import datetime, date
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    import json
    from datetime import datetime, timezone
    from sqlalchemy import create_engine, Integer, Text, DateTime
    from sqlalchemy.orm import Session, mapped_column
    from scrapyard.database.base_model import Base, IntPKModel
    from scrapyard.identity.users import User

    global _ExportNote
    try:
        _ExportNote
    except NameError:
        class _ExportNote(IntPKModel):
            __tablename__ = "data_export_selftest_notes"
            user_id = mapped_column(Integer, nullable=False)
            body = mapped_column(Text, nullable=False, default="")
            at = mapped_column(DateTime(timezone=True), nullable=True)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                u = User(email="dsar@example.com", password_hash="x")
                db.add(u); db.flush()
                db.add(_ExportNote(user_id=u.id, body="hello",
                                   at=datetime(2024, 5, 1, tzinfo=timezone.utc)))
                db.commit()

                out = export_user_data(db, u.id)
                assert out["users"][0]["email"] == "dsar@example.com"
                # NEGATIVE: credentials never leave in an export payload
                assert out["users"][0]["password_hash"] == _REDACTED, \
                    "password hash leaked into DSAR export"
                assert "x" != out["users"][0]["password_hash"]
                from scrapyard.identity.session_manager import SessionManager
                from scrapyard.identity.session_manager import Session as _SessRow
                _SessRow.__table__.create(engine, checkfirst=True)  # imported after create_all
                tok = SessionManager(db).create(u.id); db.commit()
                out2 = json.dumps(export_user_data(db, u.id))
                assert tok not in out2, "live session token leaked into DSAR export"
                assert "sessions" in out2, "session metadata should still be exported"
                assert out["data_export_selftest_notes"][0]["body"] == "hello"
                # Datetimes serialized to ISO strings; whole payload JSON-safe.
                assert isinstance(out["data_export_selftest_notes"][0]["at"], str)
                json.dumps(out)

                assert export_user_data(db, 999999) == {"error": "not found"}
        finally:
            engine.dispose()
    print("data_export self-test passed")


if __name__ == "__main__":
    _selftest()
