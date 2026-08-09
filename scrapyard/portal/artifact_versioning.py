"""
artifact_versioning — ** Tracks and manages different versions of shared artifacts for the client portal, enabling audit, rollback, and versioned access. This module provides a robust, type-safe, and scalable mechanism for

### PART-META-JSON
{
  "name": "artifact_versioning",
  "layer": "portal",
  "purpose": "Tracks and manages different versions of shared artifacts for the client portal, enabling audit, rollback, and versioned access. This module provides a robust, type-safe, and scalable mechanism for.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_artifact_version(session, artifact_id, content); get_artifact_history(session, artifact_id); ArtifactVersion(...).",
  "outputs": "Returns: create_artifact_version -> ArtifactVersion; get_artifact_history -> List[ArtifactVersion].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.portal.artifact_versioning`.",
  "example": "from scrapyard.portal.artifact_versioning import *",
  "import_path": "scrapyard.portal.artifact_versioning"
}
### END-PART-META
"""
# PART-META-JSON: {"layer": "portal", "name": "artifact_versioning"}

import os
import tempfile
from datetime import datetime
from typing import List

from sqlalchemy import LargeBinary, String, DateTime, select, func, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session

from scrapyard.database.base_model import IntPKModel


class ArtifactVersion(IntPKModel):
    __tablename__ = "artifact_versions"
    
    artifact_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )


def create_artifact_version(session: Session, artifact_id: str, content: bytes) -> ArtifactVersion:
    """Create a new version of an artifact."""
    if not isinstance(artifact_id, str):
        raise TypeError("artifact_id must be a string")
    if not artifact_id:
        raise ValueError("artifact_id cannot be empty")
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    
    version = ArtifactVersion(
        artifact_id=artifact_id,
        content=content,
    )
    session.add(version)
    return version


def get_artifact_history(session: Session, artifact_id: str) -> List[ArtifactVersion]:
    """Retrieve all versions of an artifact, ordered by creation time."""
    if not isinstance(artifact_id, str):
        raise TypeError("artifact_id must be a string")
    if not artifact_id:
        raise ValueError("artifact_id cannot be empty")
    
    stmt = (
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.created_at.asc())
    )
    return list(session.scalars(stmt))


def _selftest():
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            IntPKModel.metadata.create_all(engine)
            
            session = Session(engine)
            try:
                content_v1 = b"Initial artifact content"
                version1 = create_artifact_version(session, "test-artifact", content_v1)
                assert version1.artifact_id == "test-artifact"
                assert version1.content == content_v1
                
                session.flush()
                assert version1.id is not None
                assert version1.created_at is not None
                
                history = get_artifact_history(session, "test-artifact")
                assert len(history) == 1
                assert history[0].content == content_v1
                assert isinstance(history[0].content, bytes)
                
                content_v2 = b"Updated artifact content"
                version2 = create_artifact_version(session, "test-artifact", content_v2)
                session.flush()
                
                history = get_artifact_history(session, "test-artifact")
                assert len(history) == 2
                assert history[0].content == content_v1
                assert history[1].content == content_v2
                assert history[0].created_at <= history[1].created_at
                
                other_content = b"Other artifact content"
                create_artifact_version(session, "other-artifact", other_content)
                session.flush()
                
                test_history = get_artifact_history(session, "test-artifact")
                assert len(test_history) == 2
                
                other_history = get_artifact_history(session, "other-artifact")
                assert len(other_history) == 1
                assert other_history[0].content == other_content
                
                try:
                    create_artifact_version(session, "", b"content")
                    raise AssertionError("Expected ValueError for empty artifact_id")
                except ValueError:
                    pass
                
                try:
                    create_artifact_version(session, 123, b"content")  # type: ignore
                    raise AssertionError("Expected TypeError for non-string artifact_id")
                except TypeError:
                    pass
                
                try:
                    create_artifact_version(session, "id", "not bytes")  # type: ignore
                    raise AssertionError("Expected TypeError for non-bytes content")
                except TypeError:
                    pass
                
                try:
                    get_artifact_history(session, "")
                    raise AssertionError("Expected ValueError for empty artifact_id")
                except ValueError:
                    pass
                
                try:
                    get_artifact_history(session, 123)  # type: ignore
                    raise AssertionError("Expected TypeError for non-string artifact_id")
                except TypeError:
                    pass
                
            finally:
                session.rollback()
                session.close()
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
