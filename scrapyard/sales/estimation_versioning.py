"""
estimation_versioning — ** Tracks and manages estimate versions for audit and comparison, enabling traceability and rollback in pricing workflows. Provides a robust versioning mechanism with history tracking and controlled r

### PART-META-JSON
{
  "name": "estimation_versioning",
  "layer": "sales",
  "purpose": "Tracks and manages estimate versions for audit and comparison, enabling traceability and rollback in pricing workflows. Provides a robust versioning mechanism with history tracking and controlled r.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure(engine); save_estimate_version(estimate_id, data, user_id); get_estimate_history(estimate_id); revert_to_version(version_id); EstimateVersion(...); EstimateChangeLog(...).",
  "outputs": "Returns: configure -> None; save_estimate_version -> int; get_estimate_history -> list[EstimateVersion]; revert_to_version -> dict.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.sales.estimation_versioning`.",
  "example": "from scrapyard.sales.estimation_versioning import *",
  "import_path": "scrapyard.sales.estimation_versioning"
}
### END-PART-META
"""
from __future__ import annotations

from sqlalchemy import (
    Integer, Text, DateTime, JSON, 
    func, select, ForeignKey, Index, create_engine
)
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

PART_META = {
    "name": "estimation_versioning",
    "layer": "sales"
}

# Module-level engine storage
_engine = None

def configure(engine: Any) -> None:
    """Configure the module with a SQLAlchemy engine."""
    global _engine
    _engine = engine


class EstimateVersion(IntPKModel):
    """Stores versioned estimate data."""
    __tablename__ = "estimate_version"
    
    estimate_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    
    __table_args__ = (
        Index('ix_estimate_version_estimate_id_version', 'estimate_id', 'version_number'),
    )


class EstimateChangeLog(IntPKModel):
    """Logs changes between versions."""
    __tablename__ = "estimate_change_log"
    
    version_id: Mapped[int] = mapped_column(
        ForeignKey("estimate_version.id", ondelete="CASCADE"), 
        nullable=False,
        index=True
    )
    previous_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("estimate_version.id", ondelete="SET NULL"), 
        nullable=True
    )
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )


def _calculate_diff(old_data: Dict[str, Any], new_data: Dict[str, Any]) -> str:
    """Calculate a simple text diff between two data dictionaries."""
    changes = []
    old_keys = set(old_data.keys())
    new_keys = set(new_data.keys())
    
    added = new_keys - old_keys
    removed = old_keys - new_keys
    common = old_keys & new_keys
    
    for key in sorted(added):
        changes.append(f"Added {key}: {new_data[key]}")
    for key in sorted(removed):
        changes.append(f"Removed {key}: {old_data[key]}")
    for key in sorted(common):
        if old_data[key] != new_data[key]:
            changes.append(f"Changed {key}: {old_data[key]} -> {new_data[key]}")
    
    return "; ".join(changes) if changes else "No changes detected"


def save_estimate_version(estimate_id: int, data: dict, user_id: int) -> int:
    """
    Save a new version of an estimate.
    
    Returns:
        int: The ID of the newly created version.
    """
    if _engine is None:
        raise RuntimeError("Module not configured with engine. Call configure() first.")
    
    with Session(_engine) as session:
        # Determine next version number for this estimate
        result = session.execute(
            select(func.max(EstimateVersion.version_number))
            .where(EstimateVersion.estimate_id == estimate_id)
        )
        max_version = result.scalar() or 0
        next_version_num = max_version + 1
        
        # Create new version
        version = EstimateVersion(
            estimate_id=estimate_id,
            data=data,
            user_id=user_id,
            version_number=next_version_num
        )
        session.add(version)
        session.flush()  # Get ID without committing
        
        # Find previous version for change logging
        prev_version = session.execute(
            select(EstimateVersion)
            .where(EstimateVersion.estimate_id == estimate_id)
            .where(EstimateVersion.version_number < next_version_num)
            .order_by(EstimateVersion.version_number.desc())
        ).scalar_one_or_none()
        
        # Create change log entry
        if prev_version:
            summary = _calculate_diff(prev_version.data, data)
            change_log = EstimateChangeLog(
                version_id=version.id,
                previous_version_id=prev_version.id,
                change_summary=summary
            )
        else:
            change_log = EstimateChangeLog(
                version_id=version.id,
                previous_version_id=None,
                change_summary="Initial version"
            )
        
        session.add(change_log)
        session.commit()
        
        return version.id


def get_estimate_history(estimate_id: int) -> list[EstimateVersion]:
    """
    Retrieve full history of versions for a given estimate ID.
    
    Returns:
        List of EstimateVersion objects ordered by version number ascending.
    """
    if _engine is None:
        raise RuntimeError("Module not configured with engine. Call configure() first.")
    
    with Session(_engine) as session:
        result = session.execute(
            select(EstimateVersion)
            .where(EstimateVersion.estimate_id == estimate_id)
            .order_by(EstimateVersion.version_number.asc())
        )
        return list(result.scalars().all())


def revert_to_version(version_id: int) -> dict:
    """
    Revert to a prior version by creating a new version with the same data.
    
    Args:
        version_id: The ID of the version to revert to.
        
    Returns:
        dict: The data of the reverted version (now the current version).
        
    Raises:
        ValueError: If the version_id is not found.
    """
    if _engine is None:
        raise RuntimeError("Module not configured with engine. Call configure() first.")
    
    with Session(_engine) as session:
        # Fetch the target version
        target_version = session.get(EstimateVersion, version_id)
        if target_version is None:
            raise ValueError(f"Version {version_id} not found")
        
        # Determine next version number
        result = session.execute(
            select(func.max(EstimateVersion.version_number))
            .where(EstimateVersion.estimate_id == target_version.estimate_id)
        )
        max_version = result.scalar() or 0
        next_version_num = max_version + 1
        
        # Create new version with reverted data
        # Use user_id=0 to indicate system revert since API doesn't specify user
        new_version = EstimateVersion(
            estimate_id=target_version.estimate_id,
            data=target_version.data,
            user_id=0,  # System user for revert operations
            version_number=next_version_num
        )
        session.add(new_version)
        session.flush()
        
        # Log the revert operation
        change_log = EstimateChangeLog(
            version_id=new_version.id,
            previous_version_id=target_version.id,
            change_summary=f"Reverted to version {target_version.version_number} (id: {target_version.id})"
        )
        session.add(change_log)
        session.commit()
        
        return dict(new_version.data)


def _selftest():
    """
    Offline self-test using temporary SQLite database.
    Validates saving, history retrieval, reverting, and change logging.
    """
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        test_engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            # Create tables
            IntPKModel.metadata.create_all(test_engine)
            configure(test_engine)
            
            # Test data
            est_id = 42
            user_1 = 100
            user_2 = 200
            
            # Test 1: Save initial version
            data_v1 = {"total": 1000.0, "items": ["part_a", "part_b"], "status": "draft"}
            v1_id = save_estimate_version(est_id, data_v1, user_1)
            assert isinstance(v1_id, int), "Version ID should be an integer"
            assert v1_id > 0, "Version ID should be positive"
            
            # Test 2: Save second version
            data_v2 = {"total": 1200.0, "items": ["part_a", "part_b", "part_c"], "status": "review"}
            v2_id = save_estimate_version(est_id, data_v2, user_2)
            assert isinstance(v2_id, int), "Second version ID should be an integer"
            assert v2_id != v1_id, "Version IDs should be unique"
            
            # Test 3: Retrieve history
            history = get_estimate_history(est_id)
            assert len(history) == 2, f"Expected 2 versions, got {len(history)}"
            assert history[0].version_number == 1, "First version should have number 1"
            assert history[1].version_number == 2, "Second version should have number 2"
            assert history[0].data == data_v1, "First version data mismatch"
            assert history[1].data == data_v2, "Second version data mismatch"
            assert history[0].user_id == user_1, "First version user ID mismatch"
            assert history[1].user_id == user_2, "Second version user ID mismatch"
            
            # Test 4: Verify change log entries
            with Session(test_engine) as session:
                logs = session.execute(select(EstimateChangeLog)).scalars().all()
                assert len(logs) == 2, f"Expected 2 change log entries, got {len(logs)}"
                
                # Check first version log (initial)
                log1 = [l for l in logs if l.version_id == v1_id][0]
                assert log1.previous_version_id is None, "Initial version should have no previous"
                assert "Initial" in (log1.change_summary or ""), "Should indicate initial version"
                
                # Check second version log (has diff)
                log2 = [l for l in logs if l.version_id == v2_id][0]
                assert log2.previous_version_id == v1_id, "Should reference previous version"
                assert log2.change_summary is not None, "Change summary should exist"
                assert "total" in log2.change_summary or "Changed" in log2.change_summary, "Should detect changes"
            
            # Test 5: Revert to first version
            reverted_data = revert_to_version(v1_id)
            assert reverted_data == data_v1, "Reverted data should match original v1 data"
            
            # Verify history after revert
            history_after = get_estimate_history(est_id)
            assert len(history_after) == 3, f"Expected 3 versions after revert, got {len(history_after)}"
            assert history_after[2].version_number == 3, "Reverted version should be version 3"
            assert history_after[2].data == data_v1, "Reverted version data should match v1"
            assert history_after[2].user_id == 0, "Revert should use system user_id"
            
            # Verify revert was logged
            with Session(test_engine) as session:
                revert_logs = session.execute(
                    select(EstimateChangeLog)
                    .where(EstimateChangeLog.version_id == history_after[2].id)
                ).scalars().all()
                assert len(revert_logs) == 1, "Should have exactly one log entry for revert"
                assert "Reverted" in revert_logs[0].change_summary, "Should indicate revert operation"
                assert revert_logs[0].previous_version_id == v1_id, "Revert should reference target version"
            
            # Test 6: Error handling - revert non-existent version
            try:
                revert_to_version(99999)
                assert False, "Should have raised ValueError for non-existent version"
            except ValueError as e:
                assert "99999" in str(e), "Error message should contain version ID"
            
            logger.info("_selftest passed successfully")
            
        finally:
            test_engine.dispose()
            global _engine
            _engine = None


if __name__ == "__main__":
    _selftest()
