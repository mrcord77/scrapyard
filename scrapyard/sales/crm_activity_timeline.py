"""
crm_activity_timeline — ** The `scrapyard.sales.crm_activity_timeline` module provides a reusable, type-safe, and scalable way to log and retrieve CRM activity timelines, ensuring consistent tracking of entity interactions a

### PART-META-JSON
{
  "name": "crm_activity_timeline",
  "layer": "sales",
  "purpose": "Provides a reusable, type-safe, and scalable way to log and retrieve CRM activity timelines, ensuring consistent tracking of entity interactions a.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure(engine); log_activity(entity_id, activity_type, description); get_activity_log(entity_id); ActivityLog(...).",
  "outputs": "Returns: configure -> None; log_activity -> None; get_activity_log -> list[ActivityLog].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.sales.crm_activity_timeline`.",
  "example": "from scrapyard.sales.crm_activity_timeline import *",
  "import_path": "scrapyard.sales.crm_activity_timeline"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

__all__ = ["log_activity", "get_activity_log", "ActivityLog", "configure"]

# Module-level engine storage for configured database connection
_engine: Optional[Any] = None


class ActivityLog(IntPKModel):
    """ORM model representing a CRM activity log entry."""
    
    __tablename__ = "activity_log"
    
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    activity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    
    def __repr__(self) -> str:
        return (
            f"<ActivityLog(id={self.id}, entity_id={self.entity_id}, "
            f"type='{self.activity_type}')>"
        )


def configure(engine: Any) -> None:
    """
    Configure the module with a SQLAlchemy engine instance.
    
    Must be called before using log_activity or get_activity_log.
    
    Args:
        engine: SQLAlchemy Engine instance
    """
    global _engine
    _engine = engine
    logger.debug("CRM Activity Timeline configured with engine")


def log_activity(entity_id: int, activity_type: str, description: str) -> None:
    """
    Log a CRM activity for a specific entity.
    
    Args:
        entity_id: The CRM entity identifier
        activity_type: Category of activity (e.g., 'call', 'email', 'meeting')
        description: Detailed description of the activity
        
    Raises:
        RuntimeError: If module has not been configured with an engine
        TypeError: If inputs are not of expected types
        ValueError: If activity_type is empty or invalid
    """
    if _engine is None:
        raise RuntimeError(
            "CRM Activity Timeline not configured. Call configure() with a valid engine first."
        )
    
    if not isinstance(entity_id, int):
        raise TypeError(f"entity_id must be int, got {type(entity_id).__name__}")
    if not isinstance(activity_type, str):
        raise TypeError(f"activity_type must be str, got {type(activity_type).__name__}")
    if not isinstance(description, str):
        raise TypeError(f"description must be str, got {type(description).__name__}")
    if not activity_type.strip():
        raise ValueError("activity_type cannot be empty or whitespace")
    
    try:
        with Session(_engine) as session:
            entry = ActivityLog(
                entity_id=entity_id,
                activity_type=activity_type.strip(),
                description=description,
                created_at=datetime.now(timezone.utc),
            )
            session.add(entry)
            session.commit()
            logger.debug(
                f"Logged activity '{activity_type}' for entity {entity_id}"
            )
    except Exception:
        logger.exception("Failed to log activity")
        raise


def get_activity_log(entity_id: int) -> list[ActivityLog]:
    """
    Retrieve all activity log entries for a specific entity.
    
    Entries are returned ordered by creation time (ascending).
    
    Args:
        entity_id: The CRM entity identifier
        
    Returns:
        List of ActivityLog instances for the entity
        
    Raises:
        RuntimeError: If module has not been configured with an engine
        TypeError: If entity_id is not an integer
    """
    if _engine is None:
        raise RuntimeError(
            "CRM Activity Timeline not configured. Call configure() with a valid engine first."
        )
    
    if not isinstance(entity_id, int):
        raise TypeError(f"entity_id must be int, got {type(entity_id).__name__}")
    
    try:
        with Session(_engine) as session:
            stmt = (
                select(ActivityLog)
                .where(ActivityLog.entity_id == entity_id)
                .order_by(ActivityLog.created_at.asc())
            )
            results = list(session.scalars(stmt).all())
            logger.debug(f"Retrieved {len(results)} activities for entity {entity_id}")
            return results
    except Exception:
        logger.exception("Failed to retrieve activity log")
        raise


def _selftest() -> None:
    """
    Offline self-test using temporary SQLite database.
    
    Validates:
    - Table schema and column definitions
    - Input type checking and validation
    - Activity logging and retrieval
    - Empty result handling
    - Proper resource cleanup
    """
    logger.info("Starting CRM Activity Timeline self-test")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_crm_timeline.db")
        engine = create_engine(f"sqlite:///{db_path}", future=True)
        
        try:
            # Setup schema
            ActivityLog.metadata.create_all(engine)
            configure(engine)
            
            # Verify schema via direct SQLite query
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(activity_log)")
                columns = {row[1]: row[2] for row in cursor.fetchall()}
                
                assert "id" in columns, "Missing id column"
                assert "entity_id" in columns, "Missing entity_id column"
                assert "activity_type" in columns, "Missing activity_type column"
                assert "description" in columns, "Missing description column"
                assert "created_at" in columns, "Missing created_at column"
                assert columns["entity_id"].upper() in ("INTEGER", "INT")
            
            # Test input validation for log_activity
            try:
                log_activity("invalid", "call", "test")  # type: ignore
                assert False, "Expected TypeError for non-int entity_id"
            except TypeError:
                pass
            
            try:
                log_activity(1, 123, "test")  # type: ignore
                assert False, "Expected TypeError for non-str activity_type"
            except TypeError:
                pass
            
            try:
                log_activity(1, "   ", "test")
                assert False, "Expected ValueError for whitespace-only activity_type"
            except ValueError:
                pass
            
            try:
                log_activity(1, "", "test")
                assert False, "Expected ValueError for empty activity_type"
            except ValueError:
                pass
            
            # Test logging functionality
            log_activity(1, "initial_contact", "First contact with lead")
            log_activity(1, "follow_up_email", "Sent pricing information")
            log_activity(2, "meeting", "Discovery call completed")
            
            # Test retrieval functionality
            entity_1_logs = get_activity_log(1)
            assert isinstance(entity_1_logs, list)
            assert len(entity_1_logs) == 2
            assert all(isinstance(log, ActivityLog) for log in entity_1_logs)
            assert entity_1_logs[0].entity_id == 1
            assert entity_1_logs[0].activity_type == "initial_contact"
            assert entity_1_logs[1].activity_type == "follow_up_email"
            assert isinstance(entity_1_logs[0].created_at, datetime)
            assert isinstance(entity_1_logs[0].id, int)
            
            entity_2_logs = get_activity_log(2)
            assert len(entity_2_logs) == 1
            assert entity_2_logs[0].description == "Discovery call completed"
            
            # Test empty result
            entity_3_logs = get_activity_log(999)
            assert entity_3_logs == []
            
            # Test input validation for get_activity_log
            try:
                get_activity_log("invalid")  # type: ignore
                assert False, "Expected TypeError for non-int entity_id"
            except TypeError:
                pass
            
            logger.info("CRM Activity Timeline self-test completed successfully")
            
        finally:
            engine.dispose()
            # Ensure SQLite connections are closed by garbage collection context exit


if __name__ == "__main__":
    _selftest()
    print("crm_activity_timeline selftest OK")
