"""
document_versioner — ** Track and manage document versions for generated content, ensuring auditability and version control. This module provides a robust, reusable mechanism for versioning documents in any software produ

### PART-META-JSON
{
  "name": "document_versioner",
  "layer": "documents",
  "purpose": "Track and manage document versions for generated content, ensuring auditability and version control. This module provides a robust, reusable mechanism for versioning documents in any software produ.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure_engine(url); save_version(document_id, content); DocumentVersion(...).",
  "outputs": "Returns: configure_engine -> None; save_version -> Version.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.documents.document_versioner`.",
  "example": "from scrapyard.documents.document_versioner import *",
  "import_path": "scrapyard.documents.document_versioner"
}
### END-PART-META
"""
from sqlalchemy import DateTime, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
import os
import time
import logging
import tempfile

logger = logging.getLogger(__name__)

_engine = None


def configure_engine(url: str) -> None:
    """Configure the database engine for save_version operations."""
    global _engine
    _engine = create_engine(url)


class DocumentVersion(IntPKModel):
    """SQLAlchemy model for document versions."""
    __tablename__ = "document_version"
    
    id: Mapped[int] = mapped_column("version_id", primary_key=True)
    document_id: Mapped[int] = mapped_column(index=True)
    content: Mapped[bytes]
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc)
    )


Version = DocumentVersion


def save_version(document_id: int, content: bytes) -> Version:
    """Save a new version of a document with the given content."""
    if _engine is None:
        raise RuntimeError("Database engine not configured. Call configure_engine() first.")
    
    with Session(_engine, expire_on_commit=False) as session:
        version = DocumentVersion(
            document_id=document_id,
            content=content,
        )
        session.add(version)
        session.commit()
        session.expunge(version)
        return version


def _selftest() -> None:
    """Run offline self-test with temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_document_versioner.db")
        url = f"sqlite:///{db_path}"
        
        configure_engine(url)
        DocumentVersion.metadata.create_all(_engine)
        
        doc_id = 42
        content_v1 = b"Original document content"
        content_v2 = b"Updated document content"
        
        # Test save_version creates version with correct document_id and content
        version1 = save_version(doc_id, content_v1)
        assert version1.document_id == doc_id
        assert version1.content == content_v1
        assert version1.created_at is not None
        assert isinstance(version1.created_at, datetime)
        
        # Ensure distinct timestamps
        time.sleep(0.05)
        
        # Test multiple versions with distinct timestamps
        version2 = save_version(doc_id, content_v2)
        assert version2.document_id == doc_id
        assert version2.content == content_v2
        assert version2.created_at > version1.created_at
        
        # Test querying versions by document_id retrieves all stored versions
        with Session(_engine) as session:
            stmt = (
                select(DocumentVersion)
                .where(DocumentVersion.document_id == doc_id)
                .order_by(DocumentVersion.created_at)
            )
            results = list(session.execute(stmt).scalars().all())
            assert len(results) == 2
            assert results[0].content == content_v1
            assert results[1].content == content_v2
            
            # Verify isolation - different document_id
            other_doc_id = 99
            other_content = b"Different document"
            save_version(other_doc_id, other_content)
            
            stmt_other = (
                select(DocumentVersion)
                .where(DocumentVersion.document_id == other_doc_id)
            )
            other_results = list(session.execute(stmt_other).scalars().all())
            assert len(other_results) == 1
            assert other_results[0].content == other_content
        
        # Verify table name mapping
        assert DocumentVersion.__tablename__ == "document_version"
        
        _engine.dispose()
        logger.info("Document versioner self-test completed successfully")


if __name__ == "__main__":
    _selftest()
