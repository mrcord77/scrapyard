"""
consent_logs — Record consent grants/revocations with proof.

### PART-META-JSON
{
  "name": "consent_logs",
  "layer": "compliance",
  "purpose": "Record consent grants/revocations with proof.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: record_consent(db, user_id, purpose, granted); has_consent(db, user_id, purpose); Consent(...).",
  "outputs": "Returns: record_consent -> Consent; has_consent -> bool.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `record_consent` from `scrapyard.compliance.consent_logs` and call it as shown in `example`; run `py -m scrapyard.compliance.consent_logs` to see its offline selftest.",
  "example": "from scrapyard.compliance.consent_logs import record_consent",
  "import_path": "scrapyard.compliance.consent_logs"
}
### END-PART-META
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, func, select
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel

class Consent(IntPKModel):
    __tablename__ = "consent_logs"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    purpose: Mapped[str] = mapped_column(String(100))
    granted: Mapped[bool] = mapped_column(Boolean, default=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

def record_consent(db, user_id: int, purpose: str, granted: bool = True) -> Consent:
    c = Consent(user_id=user_id, purpose=purpose, granted=granted)
    db.add(c); db.flush(); return c

def has_consent(db, user_id: int, purpose: str) -> bool:
    rows = db.scalars(select(Consent).where(Consent.user_id == user_id,
        Consent.purpose == purpose).order_by(Consent.at.desc())).first()
    return bool(rows and rows.granted)


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                assert has_consent(db, 1, "marketing") is False

                c = record_consent(db, 1, "marketing", granted=True)
                db.commit()
                assert c.id is not None
                assert has_consent(db, 1, "marketing") is True
                # Different purpose / user unaffected
                assert has_consent(db, 1, "analytics") is False
                assert has_consent(db, 2, "marketing") is False

                # Revocation wins as the latest entry (proof trail retained)
                import time as _t
                _t.sleep(1.1)  # server_default now() has 1s resolution on SQLite
                record_consent(db, 1, "marketing", granted=False)
                db.commit()
                assert has_consent(db, 1, "marketing") is False
                rows = db.scalars(select(Consent).where(Consent.user_id == 1,
                                                        Consent.purpose == "marketing")).all()
                assert len(rows) == 2, "revocation must append, not overwrite"
        finally:
            engine.dispose()
    print("consent_logs self-test passed")


if __name__ == "__main__":
    _selftest()
