"""
revision_history — Track all revisions of an article over time, enabling audit trails and version control for knowledge base content.

### PART-META-JSON
{
  "name": "revision_history",
  "layer": "knowledge",
  "purpose": "Track all revisions of an article over time, enabling audit trails and version control for knowledge base content.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure(engine); log_revision(article_id, content, user_id); get_article_history(article_id); Revision(...).",
  "outputs": "Returns: configure -> None; log_revision -> Revision; get_article_history -> List[Revision].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.knowledge.revision_history`.",
  "example": "from scrapyard.knowledge.revision_history import *",
  "import_path": "scrapyard.knowledge.revision_history"
}
### END-PART-META
"""

from sqlalchemy import Integer, Text, DateTime, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, List, Any
import os
import tempfile
import time
import logging

logger = logging.getLogger(__name__)

_engine: Optional[Any] = None


def configure(engine: Optional[Any]) -> None:
    """Configure the module with a SQLAlchemy engine."""
    global _engine
    _engine = engine


class Revision(IntPKModel):
    """Model for tracking article revisions."""
    __tablename__ = "revision"
    
    article_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def log_revision(article_id: int, content: str, user_id: int) -> Revision:
    """Log a new revision for an article."""
    if _engine is None:
        raise RuntimeError("Engine not configured. Call configure() first.")
    
    with Session(_engine) as session:
        revision = Revision(
            article_id=article_id,
            content=content,
            user_id=user_id,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(revision)
        session.commit()
        session.refresh(revision)
        return revision


def get_article_history(article_id: int) -> List[Revision]:
    """Retrieve all revisions for a given article, ordered by timestamp ascending."""
    if _engine is None:
        raise RuntimeError("Engine not configured. Call configure() first.")
    
    with Session(_engine) as session:
        stmt = select(Revision).where(
            Revision.article_id == article_id
        ).order_by(Revision.timestamp.asc())
        
        result = session.execute(stmt).scalars().all()
        return list(result)


def _selftest() -> None:
    """Offline selftest with temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        configure(engine)
        IntPKModel.metadata.create_all(engine)
        
        try:
            # Test: Empty history for non-existent article
            history = get_article_history(999)
            assert history == [], "Should return empty list for non-existent article"
            
            # Test: Log single revision
            rev1 = log_revision(1, "Initial content", 100)
            assert rev1.id is not None
            assert rev1.article_id == 1
            assert rev1.content == "Initial content"
            assert rev1.user_id == 100
            assert isinstance(rev1.timestamp, datetime)
            
            # Test: Retrieve history returns correct revision
            history = get_article_history(1)
            assert len(history) == 1
            assert history[0].content == "Initial content"
            assert history[0].user_id == 100
            
            # Test: Multiple revisions ordered by timestamp
            time.sleep(0.01)
            rev2 = log_revision(1, "Updated content", 101)
            time.sleep(0.01)
            rev3 = log_revision(1, "Final content", 102)
            
            history = get_article_history(1)
            assert len(history) == 3
            assert history[0].content == "Initial content"
            assert history[1].content == "Updated content"
            assert history[2].content == "Final content"
            assert history[0].user_id == 100
            assert history[1].user_id == 101
            assert history[2].user_id == 102
            assert history[0].timestamp <= history[1].timestamp <= history[2].timestamp
            
            # Test: Empty content handled correctly
            rev_empty = log_revision(2, "", 200)
            assert rev_empty.content == ""
            history_empty = get_article_history(2)
            assert len(history_empty) == 1
            assert history_empty[0].content == ""
            
            # Test: Content stored as-is without sanitization
            dangerous = "<script>alert('xss')</script>"
            rev_danger = log_revision(3, dangerous, 300)
            assert rev_danger.content == dangerous
            assert "<script>" in get_article_history(3)[0].content
            
            # Test: Article isolation
            assert len(get_article_history(1)) == 3
            assert len(get_article_history(2)) == 1
            assert len(get_article_history(3)) == 1
            
            logger.info("_selftest passed successfully")
            
        finally:
            engine.dispose()
            configure(None)


if __name__ == "__main__":
    _selftest()
