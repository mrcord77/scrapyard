"""
gdpr_dsr — Intake + fulfill data-subject requests.

### PART-META-JSON
{
  "name": "gdpr_dsr",
  "layer": "compliance",
  "purpose": "Intake and fulfill GDPR data-subject requests by routing to the compliance layer: access/export/portability return the user's full data via data_export, erasure/delete run the confirmed hard-delete cascade via account_deletion.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy",
    "scrapyard.compliance.data_export",
    "scrapyard.compliance.account_deletion"
  ],
  "inputs": "SQLAlchemy Session, user_id, request_type string (access/export/portability/erasure/delete/deletion), optional actor_user_id.",
  "outputs": "Dict with the exported data or per-table deletion counts; {'error': ...} for unknown request types or missing users.",
  "files_created": [],
  "security_notes": "Erasure requests call account_deletion.delete_account with confirm=True: a routed DSR IS the explicit confirmation, so authenticate the data subject and verify the request's legitimacy BEFORE calling handle_dsr - this function performs no identity verification itself. Export responses contain the user's complete stored data; transmit only to the verified subject.",
  "ai_usage": "Import `handle_dsr` from `scrapyard.compliance.gdpr_dsr` and call it as shown in `example`; run `py -m scrapyard.compliance.gdpr_dsr` to see its offline selftest.",
  "example": "from scrapyard.compliance.gdpr_dsr import handle_dsr",
  "import_path": "scrapyard.compliance.gdpr_dsr"
}
### END-PART-META
"""
from __future__ import annotations
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from pydantic import BaseModel
from sqlalchemy.exc import NoResultFound
import logging

logger = logging.getLogger(__name__)

STATUS = "core"

def handle_dsr(db: Session, user_id: int, request_type: str, *, actor_user_id: Optional[int] = None) -> Dict[str, Any]:
    """Route a Data Subject Request to the right handler: 'access'/'export' returns
    the data, 'erasure'/'delete' deletes it. Both are audited via the called parts."""
    from scrapyard.compliance.data_export import export_user_data
    from scrapyard.compliance.account_deletion import delete_account
    rt = request_type.lower()
    if rt in ("access", "export", "portability"):
        return {"type": rt, "data": export_user_data(db, user_id)}
    if rt in ("erasure", "delete", "deletion"):
        # A routed DSR is the explicit confirmation for the hard-delete cascade;
        # callers must have verified the data subject's identity first.
        return {"type": rt, "result": delete_account(db, user_id,
                                                     actor_user_id=actor_user_id,
                                                     confirm=True)}
    return {"error": f"unknown DSR type: {request_type}"}


def _selftest() -> None:
    """Offline test of the composed DSR flow against the repaired account_deletion."""
    import os
    import tempfile
    from sqlalchemy import create_engine, select, Integer, Text
    from sqlalchemy.orm import mapped_column

    from scrapyard.database.base_model import Base, IntPKModel
    from scrapyard.identity.users import User
    import scrapyard.admin.audit_logs  # noqa: F401 - register audit table
    import scrapyard.compliance.account_deletion  # noqa: F401 - register deletion registry table
    from scrapyard.admin.audit_logs import AuditLog

    global _DsrNote
    try:
        _DsrNote
    except NameError:
        class _DsrNote(IntPKModel):  # type: ignore[no-redef]
            __tablename__ = "gdpr_dsr_selftest_notes"
            user_id = mapped_column(Integer, nullable=False)
            body = mapped_column(Text, nullable=False, default="")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                user = User(email="subject@example.com", password_hash="x")
                db.add(user)
                db.flush()
                db.add(_DsrNote(user_id=user.id, body="note-1"))
                db.commit()
                uid = user.id

                # Access request returns the stored data.
                out = handle_dsr(db, uid, "access")
                assert out["type"] == "access"
                assert out["data"]["users"][0]["email"] == "subject@example.com"
                assert out["data"]["gdpr_dsr_selftest_notes"][0]["body"] == "note-1"

                # Unknown request type is rejected.
                assert "error" in handle_dsr(db, uid, "teleport")

                # Erasure request actually executes the confirmed cascade.
                out = handle_dsr(db, uid, "erasure", actor_user_id=1)
                db.commit()
                assert out["result"]["users"] == 1
                assert out["result"]["gdpr_dsr_selftest_notes"] == 1
                assert db.get(User, uid) is None
                assert db.execute(select(_DsrNote)
                                  .where(_DsrNote.user_id == uid)).scalars().all() == []
                # The deletion was audited.
                actions = [a.action for a in db.execute(select(AuditLog)).scalars()]
                assert "account_deletion" in actions

                # Erasure of a missing user reports the error.
                assert handle_dsr(db, 999999, "delete")["result"] == {"error": "not found"}
        finally:
            engine.dispose()

    print("gdpr_dsr self-test passed")


if __name__ == "__main__":
    _selftest()
