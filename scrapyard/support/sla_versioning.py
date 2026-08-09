"""
sla_versioning — Track and manage SLA versioning to ensure auditability and rollback capability. Enables structured handling of SLA changes across time.

### PART-META-JSON
{
  "name": "sla_versioning",
  "layer": "support",
  "purpose": "Track and manage SLA versioning to ensure auditability and rollback capability. Enables structured handling of SLA changes across time.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "scrapyard.database.base_model",
    "sqlalchemy.orm",
    "sqlalchemy.sql"
  ],
  "inputs": "Public API: create_version(sla_id, content, user_id); get_version_history(sla_id); SLAVersion(...); VersionHistory(...).",
  "outputs": "Returns: create_version -> SLAVersion; get_version_history -> List[VersionHistory].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.sla_versioning`.",
  "example": "from scrapyard.support.sla_versioning import *",
  "import_path": "scrapyard.support.sla_versioning"
}
### END-PART-META
"""

from sqlalchemy import Integer, Text, DateTime, JSON, select, ForeignKey, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import List
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

# Module-level engine placeholder; configured at runtime by caller or _selftest
_engine = None


class SLAVersion(IntPKModel):
    """Immutable record of an SLA definition version."""
    __tablename__ = "sla_versions"
    
    sla_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)


class VersionHistory(IntPKModel):
    """Audit trail for SLA version changes."""
    __tablename__ = "version_history"
    
    version_id: Mapped[int] = mapped_column(ForeignKey("sla_versions.id"), nullable=False, index=True)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="Version created")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def _get_session() -> Session:
    """Obtain a Session bound to the configured engine."""
    if _engine is None:
        raise RuntimeError("Database engine not configured")
    return Session(bind=_engine)


def create_version(sla_id: int, content: dict, user_id: int) -> SLAVersion:
    """Create a new SLA version and record the change in history."""
    session = _get_session()
    try:
        # Create version record
        version = SLAVersion(
            sla_id=sla_id,
            content=content,
            user_id=user_id
        )
        session.add(version)
        session.flush()  # Populate version.id without committing
        
        # Create corresponding history entry
        history = VersionHistory(
            version_id=version.id,
            change_summary=f"Created version for SLA {sla_id}",
            user_id=user_id
        )
        session.add(history)
        
        session.commit()
        session.refresh(version)
        return version
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_version_history(sla_id: int) -> List[VersionHistory]:
    """Query version history entries for a specific SLA ID."""
    session = _get_session()
    try:
        stmt = select(VersionHistory).join(SLAVersion).where(SLAVersion.sla_id == sla_id)
        result = session.execute(stmt)
        return [row[0] for row in result]
    finally:
        session.close()


def _selftest():
    """Offline self-test using temporary SQLite database."""
    global _engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        test_engine = create_engine(f"sqlite:///{db_path}", echo=False)
        _engine = test_engine
        
        try:
            # Verify schema creation
            IntPKModel.metadata.create_all(test_engine)

            # Test creating and retrieving SLA versions
            version1 = create_version(sla_id=1, content={"service_level": "gold"}, user_id=101)
            assert isinstance(version1, SLAVersion), "SLA version creation failed"
            
            version2 = create_version(sla_id=1, content={"service_level": "silver"}, user_id=102)
            assert isinstance(version2, SLAVersion), "SLA version creation failed"

            # Test querying version history for a given SLA
            versions = get_version_history(sla_id=1)
            assert len(versions) == 2, f"Expected 2 history entries, got {len(versions)}"
            
            # Ensure version content is immutable (stored correctly)
            session = _get_session()
            try:
                version1_row = session.get(SLAVersion, version1.id)
                assert version1_row.content == {"service_level": "gold"}, "Content mismatch or mutation detected"
            finally:
                session.close()

            # Validate user tracking on version creation
            for entry in versions:
                if entry.user_id not in [101, 102]:
                    raise ValueError(f"Unexpected user_id in history: {entry.user_id}")
                
        finally:
            test_engine.dispose()
            _engine = None


if __name__ == "__main__":
    _selftest()
