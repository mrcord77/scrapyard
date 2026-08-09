"""
artifact_search — ** Enables efficient, metadata-driven search for shared artifacts in a client portal, with indexing and querying capabilities. Serves as a reusable component for artifact discovery across distributed 

### PART-META-JSON
{
  "name": "artifact_search",
  "layer": "portal",
  "purpose": "Enables efficient, metadata-driven search for shared artifacts in a client portal, with indexing and querying capabilities. Serves as a reusable component for artifact discovery across distributed.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: initialize_database(connection_string); index_artifact(artifact); search_artifacts(query, filters); Artifact(...); SearchIndex(...).",
  "outputs": "Returns: initialize_database -> None; index_artifact -> None; search_artifacts -> List[Artifact].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.portal.artifact_search`.",
  "example": "from scrapyard.portal.artifact_search import *",
  "import_path": "scrapyard.portal.artifact_search"
}
### END-PART-META
"""

import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

logger = logging.getLogger(__name__)

# Database base model setup with fallback for standalone operation
try:
    from scrapyard.database.base_model import IntPKModel as BaseModel
except ImportError:
    class Base(DeclarativeBase):
        pass

    class BaseModel(Base):
        __abstract__ = True
        id: Mapped[int] = mapped_column(Integer, primary_key=True)


@dataclass
class Artifact:
    """Domain model representing an artifact to be indexed and searched."""
    id: Optional[int] = None
    name: str = ""
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None


class SearchIndex(BaseModel):
    """ORM model for the search index table storing artifact metadata and content."""
    __tablename__ = "search_index"
    
    artifact_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    
    __table_args__ = (
        Index('idx_search_name', 'name'),
    )


# Module-level state for database connection
_engine = None
_session_factory = None


def _get_session() -> Session:
    """Obtain a new database session."""
    global _session_factory
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call initialize_database() first.")
    return _session_factory()


def initialize_database(connection_string: Optional[str] = None) -> None:
    """Initialize the database engine and create tables.
    
    Args:
        connection_string: SQLAlchemy connection string. Defaults to SQLite in current directory
                          or ARTIFACT_SEARCH_DB env var.
    """
    global _engine, _session_factory
    
    if connection_string is None:
        connection_string = os.environ.get("ARTIFACT_SEARCH_DB", "sqlite:///artifact_search.db")
    
    _engine = create_engine(connection_string, echo=False, future=True)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    BaseModel.metadata.create_all(_engine)
    logger.debug(f"Initialized database at {connection_string}")


def index_artifact(artifact: Artifact) -> None:
    """Index an artifact for search, creating or updating as necessary.
    
    Args:
        artifact: The artifact to index
    """
    session = _get_session()
    try:
        stmt = select(SearchIndex).where(SearchIndex.artifact_id == str(artifact.id))
        existing = session.execute(stmt).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        
        if existing:
            existing.name = artifact.name
            existing.content = artifact.content
            existing.artifact_metadata = artifact.metadata
            existing.updated_at = now
        else:
            entry = SearchIndex(
                artifact_id=str(artifact.id),
                name=artifact.name,
                content=artifact.content,
                artifact_metadata=artifact.metadata,
                created_at=now,
                updated_at=now
            )
            session.add(entry)
        
        session.commit()
        logger.debug(f"Indexed artifact {artifact.id}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def search_artifacts(query: str, filters: dict) -> List[Artifact]:
    """Search artifacts by text query and metadata filters.
    
    Args:
        query: Full-text search string (searches name and content)
        filters: Dictionary of metadata key-value pairs to filter by
    
    Returns:
        List of matching Artifact objects
    """
    session = _get_session()
    try:
        stmt = select(SearchIndex)
        
        # Full-text search on name and content (case-insensitive)
        if query:
            pattern = f"%{query.lower()}%"
            stmt = stmt.where(
                (func.lower(SearchIndex.name).like(pattern)) |
                (func.lower(SearchIndex.content).like(pattern))
            )
        
        # Metadata filtering using JSON extraction
        for key, value in filters.items():
            json_path = f"$.{key}"
            stmt = stmt.where(func.json_extract(SearchIndex.artifact_metadata, json_path) == value)
        
        rows = session.execute(stmt).scalars().all()
        results = []
        for row in rows:
            results.append(Artifact(
                id=int(row.artifact_id) if row.artifact_id.isdigit() else row.artifact_id,
                name=row.name,
                content=row.content,
                metadata=dict(row.artifact_metadata) if row.artifact_metadata else {},
                created_at=row.created_at
            ))
        
        return results
    finally:
        session.close()


def _selftest():
    """Offline self-test using temporary SQLite database."""
    global _engine, _session_factory
    
    # Reset module state for clean test
    _engine = None
    _session_factory = None
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_artifact_search.db")
        connection_string = f"sqlite:///{db_path}"
        
        # Initialize and verify schema creation
        initialize_database(connection_string)
        
        # Create test artifacts
        artifacts = [
            Artifact(
                id=1,
                name="Hydraulic Pump",
                content="High pressure hydraulic pump for industrial machinery",
                metadata={"category": "hydraulics", "status": "active", "priority": 1}
            ),
            Artifact(
                id=2,
                name="Electric Motor",
                content="5HP electric motor with thermal protection",
                metadata={"category": "electrical", "status": "active", "priority": 2}
            ),
            Artifact(
                id=3,
                name="Hydraulic Valve",
                content="Control valve for hydraulic systems",
                metadata={"category": "hydraulics", "status": "inactive", "priority": 1}
            ),
        ]
        
        # Test indexing
        for artifact in artifacts:
            index_artifact(artifact)
        
        # Test 1: Retrieve all artifacts
        all_results = search_artifacts("", {})
        assert len(all_results) == 3, f"Expected 3 artifacts, got {len(all_results)}"
        
        # Test 2: Full-text search in content
        hydraulic_results = search_artifacts("hydraulic", {})
        assert len(hydraulic_results) == 2, f"Expected 2 hydraulic matches, got {len(hydraulic_results)}"
        
        # Test 3: Full-text search in name (case insensitive)
        motor_results = search_artifacts("MOTOR", {})
        assert len(motor_results) == 1, f"Expected 1 motor match, got {len(motor_results)}"
        assert motor_results[0].name == "Electric Motor"
        
        # Test 4: Metadata filtering
        active_results = search_artifacts("", {"status": "active"})
        assert len(active_results) == 2, f"Expected 2 active artifacts, got {len(active_results)}"
        
        # Test 5: Metadata filtering with specific category
        hydraulics = search_artifacts("", {"category": "hydraulics"})
        assert len(hydraulics) == 2, f"Expected 2 hydraulics, got {len(hydraulics)}"
        
        # Test 6: Combined text search and metadata filter
        combined = search_artifacts("pump", {"category": "hydraulics"})
        assert len(combined) == 1, f"Expected 1 combined match, got {len(combined)}"
        assert combined[0].id == 1
        
        # Test 7: Verify table schema via direct SQLite query
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            
            # Verify table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='search_index'")
            tables = cursor.fetchall()
            assert len(tables) == 1, "search_index table must exist"
            
            # Verify columns
            cursor.execute("PRAGMA table_info(search_index)")
            columns = {row[1] for row in cursor.fetchall()}
            expected_cols = {"id", "artifact_id", "name", "content", "artifact_metadata", "created_at", "updated_at"}
            assert expected_cols.issubset(columns), f"Missing columns: {expected_cols - columns}"
        finally:
            conn.close()
        
        logger.info("All self-tests passed")


if __name__ == "__main__":
    _selftest()
