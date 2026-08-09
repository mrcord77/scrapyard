"""
metadata_generator — ** The `metadata_generator` module generates structured metadata for dataset versions and splits, enabling reproducible and auditable ML workflows. It integrates with dataset versioning to ensure man

### PART-META-JSON
{
  "name": "metadata_generator",
  "layer": "ml",
  "purpose": "Generates structured metadata for dataset versions and splits, enabling reproducible and auditable ML workflows. It integrates with dataset versioning to ensure man.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: generate_metadata(version_id, split); Metadata(...); MetadataGenerator(...).",
  "outputs": "Returns: generate_metadata -> Metadata.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import what you need from `scrapyard.ml.metadata_generator`.",
  "example": "from scrapyard.ml.metadata_generator import *",
  "import_path": "scrapyard.ml.metadata_generator"
}
### END-PART-META
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.orm import Mapped, Session, declarative_base, mapped_column, sessionmaker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Metadata:
    """Immutable metadata for a dataset version split."""
    version_id: UUID
    split: str
    created_at: datetime
    schema_hash: str
    entries: List[Dict[str, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary representation."""
        return {
            "version_id": str(self.version_id),
            "split": self.split,
            "created_at": self.created_at.isoformat(),
            "schema_hash": self.schema_hash,
            "entries": self.entries,
            "metadata": self.metadata,
        }


class MetadataGenerator:
    """Generator for creating and validating dataset metadata."""
    
    def __init__(
        self,
        session: Optional[Session] = None,
        schema_validator: Optional[Callable[[Metadata], bool]] = None,
    ) -> None:
        """Initialize the metadata generator.
        
        Args:
            session: SQLAlchemy session for database queries (read-only).
            schema_validator: Optional custom validator for metadata schema.
        """
        self.session = session
        self.schema_validator = schema_validator
        self._logger = logging.getLogger(__name__)
    
    def generate(self, version_id: UUID, split: str) -> Metadata:
        """Generate a metadata for the specified version and split.
        
        Args:
            version_id: The UUID of the dataset version.
            split: The data split (train, validation, or test).
            
        Returns:
            A Metadata object containing version and split information.
            
        Raises:
            ValueError: If inputs are invalid.
        """
        if not isinstance(version_id, UUID):
            raise ValueError(f"version_id must be UUID, got {type(version_id)}")
        
        valid_splits = {"train", "validation", "test"}
        if split not in valid_splits:
            raise ValueError(f"split must be one of {valid_splits}, got {split}")
        
        created_at = datetime.now(timezone.utc)
        
        schema_data = {
            "version_id": str(version_id),
            "split": split,
            "schema_version": "1.0.0",
        }
        schema_hash = hashlib.sha256(
            json.dumps(schema_data, sort_keys=True).encode()
        ).hexdigest()
        
        entries: List[Dict[str, Any]] = []
        
        metadata = Metadata(
            version_id=version_id,
            split=split,
            created_at=created_at,
            schema_hash=schema_hash,
            entries=entries,
            metadata={"generator": "MetadataGenerator"},
        )
        
        self.validate(metadata)
        return metadata
    
    def validate(self, metadata: Metadata) -> bool:
        """Validate metadata structure and content.
        
        Args:
            metadata: The metadata to validate.
            
        Returns:
            True if validation passes.
            
        Raises:
            ValueError: If validation fails.
        """
        if not isinstance(metadata.version_id, UUID):
            raise ValueError("version_id must be a UUID")
        
        if metadata.split not in {"train", "validation", "test"}:
            raise ValueError(f"Invalid split: {metadata.split}")
        
        if not isinstance(metadata.schema_hash, str) or len(metadata.schema_hash) != 64:
            raise ValueError("schema_hash must be a 64-character SHA-256 hex string")
        
        if self.schema_validator is not None:
            if not self.schema_validator(metadata):
                raise ValueError("Custom schema validation failed")
        
        return True


def generate_metadata(version_id: UUID, split: str) -> Metadata:
    """Generate a metadata for a dataset version and split.
    
    Convenience function that creates a MetadataGenerator with no database 
    session and generates the metadata.
    
    Args:
        version_id: The UUID of the dataset version.
        split: The data split (train, validation, or test).
        
    Returns:
        A Metadata object.
    """
    generator = MetadataGenerator(session=None)
    return generator.generate(version_id, split)


def _selftest() -> None:
    """Run offline self-test with temporary SQLite database."""
    logger.info("Starting metadata_generator self-test")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_metadata.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        Base = declarative_base()
        
        class DatasetVersion(Base):
            __tablename__ = "dataset_versions"
            
            id: Mapped[int] = mapped_column(Integer, primary_key=True)
            version_id: Mapped[str] = mapped_column(String(36))
            split: Mapped[str] = mapped_column(String(20))
            created_at: Mapped[datetime] = mapped_column(DateTime)
        
        Base.metadata.create_all(engine)
        
        test_uuid = uuid.uuid4()
        
        metadata = generate_metadata(test_uuid, "train")
        assert isinstance(metadata, Metadata)
        assert metadata.version_id == test_uuid
        assert metadata.split == "train"
        assert isinstance(metadata.created_at, datetime)
        assert len(metadata.schema_hash) == 64
        assert isinstance(metadata.entries, list)
        
        gen = MetadataGenerator()
        assert gen.validate(metadata) is True
        
        try:
            gen.generate(test_uuid, "invalid_split")
            assert False, "Should have raised ValueError for invalid split"
        except ValueError:
            pass
        
        try:
            gen.generate("not-a-uuid", "train")  # type: ignore
            assert False, "Should have raised ValueError for invalid UUID"
        except ValueError:
            pass
        
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        dv = DatasetVersion(
            version_id=str(test_uuid),
            split="train",
            created_at=datetime.now(timezone.utc)
        )
        session.add(dv)
        session.commit()
        
        commit_called = [False]
        original_commit = session.commit
        
        def mock_commit():
            commit_called[0] = True
            original_commit()
        
        session.commit = mock_commit  # type: ignore
        
        gen_with_session = MetadataGenerator(session=session)
        metadata2 = gen_with_session.generate(uuid.uuid4(), "validation")
        
        assert not commit_called[0], "Metadata generation should not commit to database"
        
        session.close()
        
        conn = sqlite3.connect(db_path)
        conn.close()
    
    logger.info("Self-test completed successfully")


if __name__ == "__main__":
    _selftest()
