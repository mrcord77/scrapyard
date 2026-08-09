"""
sync_state_tracker — Tracks and records synchronization states between systems, ensuring data consistency and providing a historical view of sync progress.

### PART-META-JSON
{
  "name": "sync_state_tracker",
  "layer": "connectors",
  "purpose": "Tracks and records synchronization states between systems, ensuring data consistency and providing a historical view of sync progress.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: track_sync_state(session, sync_id, status, details); SyncState(...); SyncStateTracker(...).",
  "outputs": "Returns: track_sync_state -> SyncState.",
  "files_created": [
    "sync_states"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.connectors.sync_state_tracker`.",
  "example": "from scrapyard.connectors.sync_state_tracker import *",
  "import_path": "scrapyard.connectors.sync_state_tracker"
}
### END-PART-META
"""

import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, JSON, String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class SyncState(IntPKModel):
    __tablename__ = "sync_states"

    sync_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


class SyncStateTracker:
    """Tracks and manages synchronization states between systems."""

    def __init__(self, session: Session):
        self.session = session
        self.logger = logging.getLogger(__name__)

    def track_sync_state(
        self, sync_id: str, status: str, details: Optional[Dict[str, Any]] = None
    ) -> SyncState:
        """Create or update a sync state record."""
        stmt = select(SyncState).where(SyncState.sync_id == sync_id)
        result = self.session.execute(stmt)
        sync_state = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if sync_state is None:
            sync_state = SyncState(
                sync_id=sync_id,
                status=status,
                created_at=now,
                updated_at=now,
                details=details,
            )
            self.session.add(sync_state)
            self.logger.info(f"Created sync state: sync_id={sync_id}, status={status}")
        else:
            sync_state.status = status
            sync_state.updated_at = now
            if details is not None:
                sync_state.details = details
            self.logger.info(f"Updated sync state: sync_id={sync_id}, status={status}")

        self.session.commit()
        return sync_state


def track_sync_state(
    session: Session, sync_id: str, status: str, details: Optional[Dict[str, Any]] = None
) -> SyncState:
    """Convenience function to track sync state using a temporary tracker instance."""
    tracker = SyncStateTracker(session)
    return tracker.track_sync_state(sync_id, status, details)


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)

        # Initialize schema
        IntPKModel.metadata.create_all(engine)

        # Test with session context
        with Session(engine) as session:
            # Test SyncStateTracker creates sync states
            tracker = SyncStateTracker(session)
            state1 = tracker.track_sync_state("sync-test-1", "pending")
            assert state1.sync_id == "sync-test-1"
            assert state1.status == "pending"
            assert state1.created_at is not None
            assert state1.updated_at is not None
            assert state1.id is not None

            # Test retrieval of existing state (should update)
            state1_retrieved = tracker.track_sync_state("sync-test-1", "pending")
            assert state1_retrieved.id == state1.id

            # Test track_sync_state updates existing sync states
            state_updated = track_sync_state(
                session, "sync-test-1", "completed", {"progress": 100}
            )
            assert state_updated.id == state1.id
            assert state_updated.status == "completed"
            assert state_updated.details == {"progress": 100}

            # Test creating additional sync states
            state2 = track_sync_state(session, "sync-test-2", "running")
            assert state2.sync_id == "sync-test-2"
            assert state2.status == "running"
            assert state2.details is None

            # Verify persistence by querying fresh from database
            stmt = select(SyncState).where(SyncState.sync_id == "sync-test-1")
            persisted = session.execute(stmt).scalar_one()
            assert persisted.status == "completed"
            assert persisted.details == {"progress": 100}

            # Verify multiple states exist
            all_states = session.execute(select(SyncState)).scalars().all()
            assert len(all_states) == 2

        engine.dispose()


if __name__ == "__main__":
    _selftest()
