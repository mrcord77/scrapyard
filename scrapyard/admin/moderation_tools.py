"""
moderation_tools — Flag/review/resolve user-generated content.

### PART-META-JSON
{
  "name": "moderation_tools",
  "layer": "admin",
  "purpose": "Flag/review/resolve user-generated content.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: flag(db, target, reason, *, actor_user_id); resolve(db, flag_id, status); open_flags(db); ModerationFlag(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `flag` from `scrapyard.admin.moderation_tools` and call it as shown in `example`; run `py -m scrapyard.admin.moderation_tools` to see its offline selftest.",
  "example": "from scrapyard.admin.moderation_tools import flag",
  "import_path": "scrapyard.admin.moderation_tools"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
from sqlalchemy import String, Integer, Text, DateTime, func, select
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
class ModerationFlag(IntPKModel):
    __tablename__="moderation_flags"
    target: Mapped[str]=mapped_column(String(200), index=True)
    reason: Mapped[str]=mapped_column(Text, default=""); status: Mapped[str]=mapped_column(String(20), default="open")
    at: Mapped[datetime]=mapped_column(DateTime(timezone=True), server_default=func.now())
def flag(db, target, reason, *, actor_user_id=None):
    from scrapyard.admin.audit_logs import record
    f=ModerationFlag(target=target, reason=reason); db.add(f)
    record(db, action="content_flagged", actor_user_id=actor_user_id, target=target, detail=reason)
    db.flush(); return f
def resolve(db, flag_id, status="resolved"):
    f=db.get(ModerationFlag, flag_id)
    if f: f.status=status; db.flush()
    return f
def open_flags(db):
    return list(db.scalars(select(ModerationFlag).where(ModerationFlag.status=="open")))


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from scrapyard.database.base_model import Base
    import scrapyard.admin.audit_logs  # noqa: F401
    from scrapyard.admin.audit_logs import AuditLog

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                f1 = flag(db, "post:1", "spam", actor_user_id=7)
                f2 = flag(db, "post:2", "abuse")
                db.commit()
                assert f1.status == "open" and f2.status == "open"
                assert {f.target for f in open_flags(db)} == {"post:1", "post:2"}

                resolved = resolve(db, f1.id)
                db.commit()
                assert resolved.status == "resolved"
                assert [f.target for f in open_flags(db)] == ["post:2"]

                assert resolve(db, 99999) is None
                assert resolve(db, f2.id, status="dismissed").status == "dismissed"
                assert open_flags(db) == []

                # Flagging is audited
                actions = [a.action for a in db.scalars(select(AuditLog))]
                assert actions.count("content_flagged") == 2
        finally:
            engine.dispose()
    print("moderation_tools self-test passed")


if __name__ == "__main__":
    _selftest()
