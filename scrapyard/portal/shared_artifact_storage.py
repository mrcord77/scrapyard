"""Shared artifact storage for the scrapyard portal domain.

Provides type-safe CRUD for artifacts and their metadata backed by SQLAlchemy.

### PART-META-JSON
{
  "name": "shared_artifact_storage",
  "layer": "portal",
  "purpose": "Store and retrieve binary artifacts with key/value metadata: upload_artifact() persists file bytes with SHA-256 content hash, generated uuid artifact id, size, and linked ArtifactMetadata rows (unique key per artifact); get_artifact_by_id() returns a frozen Artifact dataclass or None. A unique constraint on content_hash rejects byte-identical duplicates with ValueError.",
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "upload_artifact(File(name, content_type, data_bytes), metadata_dict); get_artifact_by_id(artifact_id).",
  "outputs": "Artifact dataclasses; artifacts + artifact_metadata tables (ArtifactRecord/ArtifactMetadata ORM rows).",
  "files_created": [],
  "security_notes": "Artifact bytes are stored verbatim in the DB with no size cap, content-type validation, or malware scanning - enforce upload limits and type checks upstream, and never serve stored bytes back with a caller-controlled content_type without sanitizing. The GLOBAL unique content-hash lets any uploader probe whether some exact content already exists (duplicate -> ValueError), which is an information leak in multi-tenant use; scope or salt hashes if that matters. Default engine is an in-memory SQLite (non-persistent, single-process) - inject a real engine via _set_engine for durable storage. No authentication or per-artifact access control here.",
  "ai_usage": "art = upload_artifact(File('a.png', 'image/png', data), {'project': 'x'}); later get_artifact_by_id(art.id).",
  "example": "from scrapyard.portal.shared_artifact_storage import File, upload_artifact, get_artifact_by_id",
  "import_path": "scrapyard.portal.shared_artifact_storage"
}
### END-PART-META
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, selectinload
from sqlalchemy.pool import StaticPool

try:
    from scrapyard.database.base_model import IntPKModel
except Exception:  # pragma: no cover
    from sqlalchemy.orm import DeclarativeBase

    class IntPKModel(DeclarativeBase):
        id: Mapped[int] = mapped_column(primary_key=True)


logger = logging.getLogger(__name__)

__all__ = ["File", "Artifact", "upload_artifact", "get_artifact_by_id"]


# ------------------------------------------------------------------------------
# Public data types
# ------------------------------------------------------------------------------


@dataclass(frozen=True)
class File:
    """A simple file representation accepted by the storage API."""

    name: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class Artifact:
    """A stored artifact with its metadata."""

    id: str
    name: str
    content_type: str
    data: bytes
    size: int
    metadata: Dict[str, Any]
    created_at: datetime


# ------------------------------------------------------------------------------
# ORM models
# ------------------------------------------------------------------------------


class ArtifactRecord(IntPKModel):
    """Binary artifact storage."""

    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    metadata_entries: Mapped[List["ArtifactMetadata"]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_artifacts_content_hash"),
    )


class ArtifactMetadata(IntPKModel):
    """Key/value metadata linked to an artifact."""

    __tablename__ = "artifact_metadata"

    artifact_record_id: Mapped[int] = mapped_column(
        ForeignKey("artifacts.id"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)

    artifact: Mapped["ArtifactRecord"] = relationship(
        back_populates="metadata_entries"
    )

    __table_args__ = (
        UniqueConstraint(
            "artifact_record_id",
            "key",
            name="uq_artifact_metadata_key",
        ),
    )


# ------------------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------------------


_engine: Optional[Any] = None


def _get_engine() -> Any:
    """Return the configured engine, lazily creating an in-memory one."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            "sqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        ArtifactRecord.metadata.create_all(_engine)
    return _engine


def _set_engine(engine: Any) -> None:
    """Configure a specific engine (used by the self-test)."""
    global _engine
    _engine = engine


def _get_session() -> Session:
    return Session(bind=_get_engine())


def _to_artifact(record: ArtifactRecord) -> Artifact:
    metadata = {entry.key: entry.value for entry in record.metadata_entries}
    return Artifact(
        id=record.artifact_id,
        name=record.name,
        content_type=record.content_type,
        data=record.data,
        size=record.size,
        metadata=metadata,
        created_at=record.created_at,
    )


# ------------------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------------------


def upload_artifact(artifact: File, metadata: dict) -> Artifact:
    """Store an artifact and its metadata.

    Args:
        artifact: The file to store.
        metadata: A mapping of metadata keys to values.

    Returns:
        The stored artifact representation.

    Raises:
        ValueError: If an identical artifact already exists.
    """
    content_hash = hashlib.sha256(artifact.data).hexdigest()
    artifact_id = uuid.uuid4().hex

    session = _get_session()
    try:
        record = ArtifactRecord(
            artifact_id=artifact_id,
            name=artifact.name,
            content_type=artifact.content_type,
            content_hash=content_hash,
            data=artifact.data,
            size=len(artifact.data),
        )

        for key, value in metadata.items():
            record.metadata_entries.append(
                ArtifactMetadata(key=key, value=value)
            )

        session.add(record)
        session.flush()
        session.commit()

        return _to_artifact(record)
    except IntegrityError as exc:
        session.rollback()
        raise ValueError(
            "An artifact with identical content already exists."
        ) from exc
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_artifact_by_id(artifact_id: str) -> Optional[Artifact]:
    """Retrieve an artifact by its unique artifact ID.

    Args:
        artifact_id: The unique artifact identifier.

    Returns:
        The artifact if found, otherwise None.
    """
    session = _get_session()
    try:
        stmt = (
            select(ArtifactRecord)
            .where(ArtifactRecord.artifact_id == artifact_id)
            .options(selectinload(ArtifactRecord.metadata_entries))
        )
        record = session.execute(stmt).unique().scalar_one_or_none()
        return _to_artifact(record) if record is not None else None
    finally:
        session.close()


# ------------------------------------------------------------------------------
# Offline self-test
# ------------------------------------------------------------------------------


def _selftest() -> None:
    """Run an offline self-test using a temporary SQLite database."""
    import os
    import tempfile

    original_engine = _engine
    test_engine = None

    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = os.path.join(tmpdir, "shared_artifact_storage.db")
            test_engine = create_engine(f"sqlite:///{db_path}")
            _set_engine(test_engine)
            ArtifactRecord.metadata.create_all(test_engine)

            file_obj = File(
                name="blueprint.png",
                content_type="image/png",
                data=b"\x89PNG\r\n\x1a\nfake-data",
            )
            meta = {"project": "alpha", "revision": 3}

            # Upload and retrieve
            artifact = upload_artifact(file_obj, meta)
            assert isinstance(artifact, Artifact)
            assert artifact.name == file_obj.name
            assert artifact.content_type == file_obj.content_type
            assert artifact.data == file_obj.data
            assert artifact.size == len(file_obj.data)
            assert artifact.metadata == meta
            assert artifact.id

            fetched = get_artifact_by_id(artifact.id)
            assert fetched is not None
            assert fetched.id == artifact.id
            assert fetched.data == file_obj.data
            assert fetched.metadata == meta

            # Duplicate upload should raise
            raised = False
            try:
                upload_artifact(file_obj, {})
            except ValueError:
                raised = True
            assert raised, "duplicate upload did not raise ValueError"

            # Invalid ID returns None
            assert get_artifact_by_id("nonexistent-id") is None

            # Cleanup is handled by disposing the engine; TemporaryDirectory
            # will remove the file afterward.
            test_engine.dispose()
            test_engine = None
    finally:
        _set_engine(original_engine)
        if test_engine is not None:
            test_engine.dispose()


if __name__ == "__main__":
    _selftest()
