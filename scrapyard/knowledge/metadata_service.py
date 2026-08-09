"""
metadata_service — Manage custom metadata for articles and categories, enabling flexible tagging and querying. Supports structured storage, retrieval, and modification of key-value pairs tied to knowledge base entries.

### PART-META-JSON
{
  "name": "metadata_service",
  "layer": "knowledge",
  "purpose": "Manage custom metadata for articles and categories, enabling flexible tagging and querying. Supports structured storage, retrieval, and modification of key-value pairs tied to knowledge base entries.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: add_metadata(session, article_id, key, value); get_metadata(session, article_id); Metadata(...).",
  "outputs": "Returns: add_metadata -> None; get_metadata -> Dict[str, str].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.knowledge.metadata_service`.",
  "example": "from scrapyard.knowledge.metadata_service import *",
  "import_path": "scrapyard.knowledge.metadata_service"
}
### END-PART-META
"""
from sqlalchemy import String, Integer, Text, select, UniqueConstraint, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from typing import Dict
import tempfile
import os
import logging

logger = logging.getLogger(__name__)


class Metadata(IntPKModel):
    """ORM model for article metadata storage."""
    __tablename__ = 'metadata'
    
    article_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    
    __table_args__ = (
        UniqueConstraint('article_id', 'key', name='uq_metadata_article_key'),
    )


def add_metadata(session: Session, article_id: int, key: str, value: str) -> None:
    """Add or update metadata for an article.
    
    If a metadata entry with the same key already exists for the article,
    its value is overwritten.
    
    Args:
        session: SQLAlchemy database session
        article_id: ID of the article to tag
        key: Metadata key name
        value: Metadata value
        
    Raises:
        ValueError: If article_id is not a non-negative integer, 
                   key is not a non-empty string, or value is not a string
    """
    if not isinstance(article_id, int):
        raise ValueError("article_id must be an integer")
    if article_id < 0:
        raise ValueError("article_id must be non-negative")
    if not isinstance(key, str):
        raise ValueError("key must be a string")
    if not key:
        raise ValueError("key must not be empty")
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    
    stmt = select(Metadata).where(
        Metadata.article_id == article_id,
        Metadata.key == key
    )
    existing = session.execute(stmt).scalar_one_or_none()
    
    if existing is not None:
        existing.value = value
    else:
        meta = Metadata(article_id=article_id, key=key, value=value)
        session.add(meta)
    
    session.commit()


def get_metadata(session: Session, article_id: int) -> Dict[str, str]:
    """Retrieve all metadata for a given article.
    
    Args:
        session: SQLAlchemy database session
        article_id: ID of the article
        
    Returns:
        Dictionary mapping metadata keys to values
        
    Raises:
        ValueError: If article_id is not a non-negative integer
    """
    if not isinstance(article_id, int):
        raise ValueError("article_id must be an integer")
    if article_id < 0:
        raise ValueError("article_id must be non-negative")
    
    stmt = select(Metadata).where(Metadata.article_id == article_id)
    results = session.execute(stmt).scalars().all()
    
    return {meta.key: meta.value for meta in results}


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, 'test_metadata.db')
        engine = create_engine(f'sqlite:///{db_path}')
        
        IntPKModel.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        try:
            # Test: Add and retrieve metadata
            add_metadata(session, 1, "author", "John Doe")
            add_metadata(session, 1, "category", "tutorial")
            result = get_metadata(session, 1)
            assert result == {"author": "John Doe", "category": "tutorial"}
            
            # Test: Duplicate keys are overwritten
            add_metadata(session, 1, "author", "Jane Doe")
            result = get_metadata(session, 1)
            assert result["author"] == "Jane Doe"
            assert len(result) == 2
            
            # Test: Empty metadata returns empty dict
            result = get_metadata(session, 999)
            assert result == {}
            
            # Test: Multiple articles are isolated
            add_metadata(session, 2, "status", "draft")
            result1 = get_metadata(session, 1)
            result2 = get_metadata(session, 2)
            assert "status" not in result1
            assert result2 == {"status": "draft"}
            
            # Test: Invalid inputs raise ValueError
            invalid_cases = [
                (lambda: add_metadata(session, -1, "key", "val"), "negative article_id"),
                (lambda: add_metadata(session, 1.5, "key", "val"), "float article_id"),
                (lambda: add_metadata(session, 1, "", "val"), "empty key"),
                (lambda: add_metadata(session, 1, None, "val"), "none key"),
                (lambda: add_metadata(session, 1, "key", 123), "int value"),
                (lambda: get_metadata(session, -1), "negative get article_id"),
                (lambda: get_metadata(session, "abc"), "string get article_id"),
            ]
            
            for func, description in invalid_cases:
                try:
                    func()
                    assert False, f"Should have raised ValueError for {description}"
                except ValueError:
                    pass
            
            # Test: Schema constraints exist
            from sqlalchemy import inspect
            inspector = inspect(engine)
            constraints = inspector.get_unique_constraints('metadata')
            has_unique = any(
                'article_id' in c.get('column_names', []) and 'key' in c.get('column_names', [])
                for c in constraints
            )
            assert has_unique, "Unique constraint on article_id+key not found"
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
