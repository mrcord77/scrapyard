"""
proposal_version - Version proposals (append-only content snapshots) with comparison and revert support.

### PART-META-JSON
{
  "name": "proposal_version",
  "layer": "quoting",
  "purpose": "Version proposals (append-only content snapshots) with comparison and revert support.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure_engine(engine); create_version(proposal_id, content, user_id); compare_versions(v1_id, v2_id); revert_to_version(version_id).",
  "outputs": "ProposalVersion rows (table 'proposal_versions'); diff dicts; the new head version created by a revert.",
  "files_created": [],
  "security_notes": "Versions are append-only: revert creates a NEW version rather than mutating history, preserving the audit trail of who changed a quote and when. Content is stored as JSON and never executed. user_id attribution is caller-supplied - authenticate upstream, this part does not verify identity.",
  "ai_usage": "Import what you need from `scrapyard.quoting.proposal_version`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.quoting.proposal_version import create_version",
  "import_path": "scrapyard.quoting.proposal_version"
}
### END-PART-META
"""
"""scrapyard.quoting.proposal_version

Tracks and manages different versions of a proposal to enable audit,
revision, and rollback capabilities within the quoting domain.
"""

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy import JSON, DateTime, Index, Integer, create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from scrapyard.database.base_model import IntPKModel

__part_meta__ = json.dumps({
    "name": "scrapyard.quoting.proposal_version",
    "layer": "quoting",
})

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_session_factory: Optional[Callable[[], Session]] = None


def configure_engine(engine: Engine) -> None:
    """Configure the SQLAlchemy engine used by this module."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = sessionmaker(engine, expire_on_commit=False)


def _get_session() -> Session:
    if _session_factory is None:
        raise RuntimeError(
            "Database engine is not configured. Call configure_engine() first."
        )
    return _session_factory()


class ProposalVersion(IntPKModel):
    """A single snapshot of proposal content at a point in time."""

    __tablename__ = "proposal_versions"

    proposal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_proposal_versions_proposal_id_version",
            "proposal_id",
            "version_number",
        ),
    )


def _next_version_number(session: Session, proposal_id: int) -> int:
    max_version = session.scalar(
        select(func.max(ProposalVersion.version_number)).where(
            ProposalVersion.proposal_id == proposal_id
        )
    )
    return (max_version or 0) + 1


def create_version(proposal_id: int, content: dict, user_id: int) -> ProposalVersion:
    """Create a new version for the given proposal."""
    with _get_session() as session:
        with session.begin():
            version = ProposalVersion(
                proposal_id=proposal_id,
                version_number=_next_version_number(session, proposal_id),
                content=content,
                created_by=user_id,
                created_at=datetime.now(timezone.utc),
            )
            session.add(version)
        return version


def _diff(left: Any, right: Any) -> Dict[str, Any]:
    """Compute a recursive diff between two JSON-compatible structures."""
    if isinstance(left, dict) and isinstance(right, dict):
        added = {k: right[k] for k in right if k not in left}
        removed = {k: left[k] for k in left if k not in right}
        modified: Dict[str, Any] = {}
        unchanged: Dict[str, Any] = {}
        for k in left:
            if k in right:
                if left[k] == right[k]:
                    unchanged[k] = left[k]
                elif isinstance(left[k], dict) and isinstance(right[k], dict):
                    modified[k] = _diff(left[k], right[k])
                else:
                    modified[k] = [left[k], right[k]]
        return {
            "added": added,
            "removed": removed,
            "modified": modified,
            "unchanged": unchanged,
        }
    if left == right:
        return {"unchanged": left}
    return {"changed": [left, right]}


def compare_versions(v1_id: int, v2_id: int) -> dict:
    """Return a diff between two proposal versions."""
    with _get_session() as session:
        with session.begin():
            v1 = session.get(ProposalVersion, v1_id)
            v2 = session.get(ProposalVersion, v2_id)
            if v1 is None or v2 is None:
                raise ValueError("One or both version IDs do not exist")
            return {
                "version_1_id": v1.id,
                "version_2_id": v2.id,
                "proposal_id": v1.proposal_id,
                "diff": _diff(v1.content, v2.content),
            }


def revert_to_version(version_id: int) -> ProposalVersion:
    """Create a new current version that restores a prior version's content."""
    with _get_session() as session:
        with session.begin():
            source = session.get(ProposalVersion, version_id)
            if source is None:
                raise ValueError(f"Version {version_id} does not exist")
            new_version = ProposalVersion(
                proposal_id=source.proposal_id,
                version_number=_next_version_number(session, source.proposal_id),
                content=source.content,
                created_by=source.created_by,
                created_at=datetime.now(timezone.utc),
            )
            session.add(new_version)
        return new_version


def _selftest() -> None:
    """Offline self-validation using a temporary SQLite database."""
    start = time.time()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "proposal_version_selftest.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        try:
            configure_engine(engine)
            IntPKModel.metadata.create_all(engine)

            v1 = create_version(
                proposal_id=1,
                content={"price": 100, "notes": "initial"},
                user_id=42,
            )
            v2 = create_version(
                proposal_id=1,
                content={"price": 150, "notes": "initial", "status": "review"},
                user_id=42,
            )
            v3 = create_version(
                proposal_id=2,
                content={"price": 999},
                user_id=7,
            )

            assert v1.proposal_id == 1
            assert v1.version_number == 1
            assert v2.proposal_id == 1
            assert v2.version_number == 2
            assert v3.proposal_id == 2
            assert v3.version_number == 1

            comparison = compare_versions(v1.id, v2.id)
            expected_diff = {
                "added": {"status": "review"},
                "removed": {},
                "modified": {"price": [100, 150]},
                "unchanged": {"notes": "initial"},
            }
            assert comparison["version_1_id"] == v1.id
            assert comparison["version_2_id"] == v2.id
            assert comparison["proposal_id"] == 1
            assert comparison["diff"] == expected_diff

            reverted = revert_to_version(v1.id)
            assert reverted.proposal_id == 1
            assert reverted.version_number == 3
            assert reverted.content == v1.content

            with _get_session() as session:
                with session.begin():
                    latest = session.scalars(
                        select(ProposalVersion)
                        .where(ProposalVersion.proposal_id == 1)
                        .order_by(ProposalVersion.version_number.desc())
                        .limit(1)
                    ).first()
                    assert latest is not None
                    assert latest.content == v1.content
        finally:
            engine.dispose()

    assert time.time() - start < 20


if __name__ == "__main__":
    _selftest()
    print("proposal_version selftest OK")
