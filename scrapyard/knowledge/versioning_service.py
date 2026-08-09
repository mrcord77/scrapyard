"""
versioning_service — Manage article versions and allow rollbacks to previous states. Provides a versioning mechanism for knowledge articles, enabling retrieval and restoration of historical states.

### PART-META-JSON
{
  "name": "versioning_service",
  "layer": "knowledge",
  "purpose": "Manage article versions and allow rollbacks to previous states. Provides a versioning mechanism for knowledge articles, enabling retrieval and restoration of historical states.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: Article(...); VersioningService(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.knowledge.versioning_service`.",
  "example": "from scrapyard.knowledge.versioning_service import *",
  "import_path": "scrapyard.knowledge.versioning_service"
}
### END-PART-META
"""
from sqlalchemy import String, Integer, Text, DateTime, select, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional
import logging
import tempfile

logger = logging.getLogger(__name__)


class Article(IntPKModel):
    """SQLAlchemy model for article versions."""
    __tablename__ = "article_versions"
    
    article_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    
    __table_args__ = (
        UniqueConstraint('article_id', 'version', name='uq_article_version'),
    )


class VersioningService:
    def __init__(self):
        self._session: Optional[Session] = None
    
    def init_session(self, session: Session) -> None:
        """Initialize the service with a database session."""
        self._session = session
    
    def get_article_version(self, article_id: int, version: int) -> Optional[Article]:
        """Retrieve a specific version of an article by ID and version number."""
        if self._session is None:
            return None
        stmt = select(Article).where(
            Article.article_id == article_id,
            Article.version == version
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def rollback_article(self, article_id: int, version: int) -> Optional[Article]:
        """Retrieve a historical article version for rollback purposes."""
        if self._session is None:
            return None
        stmt = select(Article).where(
            Article.article_id == article_id,
            Article.version == version
        )
        return self._session.execute(stmt).scalar_one_or_none()


def _selftest():
    from sqlalchemy import create_engine
    from scrapyard.database.base_model import Base
    
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        engine = create_engine(f'sqlite:///{temp_dir.name}/test.db')
        Base.metadata.create_all(engine)
        
        with Session(engine) as session:
            service = VersioningService()
            service.init_session(session)
            
            now = datetime.now(timezone.utc)
            
            # Create version 1 of the article
            article_v1 = Article(
                article_id=1,
                version=1,
                title="Test Article",
                content="This is a test article.",
                created_at=now,
                updated_at=now
            )
            session.add(article_v1)
            session.commit()
            
            # Get the first version of the article
            versioned_article = service.get_article_version(1, 1)
            assert versioned_article is not None and versioned_article.title == "Test Article"
            
            # Create version 2 (new row, preserving history)
            article_v2 = Article(
                article_id=1,
                version=2,
                title="Test Article",
                content="Updated content.",
                created_at=now,
                updated_at=datetime.now(timezone.utc)
            )
            session.add(article_v2)
            session.commit()
            
            # Rollback to the first version
            rollbacked_article = service.rollback_article(1, 1)
            assert rollbacked_article is not None and rollbacked_article.content == "This is a test article."
            
            # Test invalid version number
            invalid_version_article = service.get_article_version(1, 999)
            assert invalid_version_article is None
            
    finally:
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
