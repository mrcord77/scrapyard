"""
skill_logging — Provide structured logging for skill execution events. Enables auditing, debugging, and performance tracking of skill operations.

### PART-META-JSON
{
  "name": "skill_logging",
  "layer": "skills",
  "purpose": "Provide structured logging for skill execution events. Enables auditing, debugging, and performance tracking of skill operations.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "skill_id, event_type, payload dict; a configured session factory.",
  "outputs": "Rows in skill_logging_logs table (uncommitted - caller owns the transaction).",
  "files_created": [],
  "security_notes": "Payloads are stored verbatim as JSON - never log secrets/PII in event payloads. log_event does not commit; an uncommitted session that rolls back loses log entries by design. Table renamed skill_logging_logs to resolve the shared-Base collision - do not rename back.",
  "ai_usage": "Import what you need from `scrapyard.skills.skill_logging`.",
  "example": "from scrapyard.skills.skill_logging import *",
  "import_path": "scrapyard.skills.skill_logging"
}
### END-PART-META
"""
from __future__ import annotations

from sqlalchemy import String, DateTime, JSON, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, Callable, get_type_hints
import threading
import logging
import os
import tempfile

# (duplicate PART_META_JSON dict removed — the docstring block above is the
# single canonical metadata for this part)
STATUS = "core"

_logger = logging.getLogger(__name__)

_session_factory: Optional[Callable[[], Session]] = None
_factory_lock = threading.Lock()


class LogEntry(IntPKModel):
    """ORM model for persistent storage of skill execution logs."""
    __tablename__ = "skill_logging_logs"
    
    skill_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )


def configure_session(session_factory: Callable[[], Session]) -> None:
    """Configure the session factory for logging operations."""
    global _session_factory
    with _factory_lock:
        _session_factory = session_factory


def get_session() -> Session:
    """Retrieve a session from the configured factory."""
    if _session_factory is None:
        raise RuntimeError("Session factory not configured. Call configure_session() first.")
    return _session_factory()


def log_event(skill_id: str, event_type: str, payload: dict) -> None:
    """
    Log a skill event to the database.
    
    Note: This function does not commit the session. The caller is responsible
    for managing the transaction lifecycle (commit/rollback).
    """
    session = get_session()
    entry = LogEntry(
        skill_id=skill_id,
        event_type=event_type,
        payload=payload,
        created_at=datetime.now(timezone.utc)
    )
    session.add(entry)


class SkillLogger:
    """
    Context-aware logger for skill-specific event logging.
    
    Provides a convenient interface for logging events associated with a
    specific skill_id without repeating the skill identifier.
    """
    
    def __init__(self, skill_id: str):
        self.skill_id = skill_id
    
    def log(self, event_type: str, payload: dict) -> None:
        """Log an event associated with this logger's skill_id."""
        log_event(self.skill_id, event_type, payload)


def _selftest():
    """Verify module functionality against specifications."""
    # Verify type hints are present
    hints = get_type_hints(log_event)
    assert 'skill_id' in hints and hints['skill_id'] is str
    assert 'event_type' in hints and hints['event_type'] is str
    assert 'payload' in hints and hints['payload'] is dict
    assert hints.get('return') is type(None)
    
    logger_hints = get_type_hints(SkillLogger.log)
    assert 'event_type' in logger_hints
    assert 'payload' in logger_hints
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create tables using the Base from IntPKModel
        from scrapyard.database.base_model import Base
        Base.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        # Configure logging to use test session
        configure_session(lambda: session)
        
        try:
            # Test: Log event is stored in logs table
            log_event("skill_001", "execution_start", {"arg1": "value1"})
            session.flush()  # Push to DB without committing
            
            result = session.execute(
                select(LogEntry).where(LogEntry.skill_id == "skill_001")
            ).scalar_one_or_none()
            
            assert result is not None, "Log entry not found in table"
            assert result.event_type == "execution_start"
            assert result.payload == {"arg1": "value1"}
            
            # Test: SkillLogger logs with correct skill_id
            skill_logger = SkillLogger("skill_002")
            skill_logger.log("custom_action", {"status": "success"})
            session.flush()
            
            result2 = session.execute(
                select(LogEntry).where(LogEntry.skill_id == "skill_002")
            ).scalar_one_or_none()
            
            assert result2 is not None, "SkillLogger entry not found"
            assert result2.skill_id == "skill_002"
            assert result2.event_type == "custom_action"
            
            # Test: No database commit occurs during logging
            # If no commit occurred, rollback should remove all entries
            session.rollback()
            
            remaining = session.execute(select(LogEntry)).scalars().all()
            assert len(remaining) == 0, "Commit occurred during logging (data persisted after rollback)"
            
            # Test: Log payload is correctly serialized (complex nested structure)
            complex_payload = {
                "nested": {"a": [1, 2, 3], "b": {"c": "d"}},
                "number": 42,
                "boolean": True,
                "null_value": None
            }
            log_event("skill_003", "complex_event", complex_payload)
            session.flush()
            
            result3 = session.execute(
                select(LogEntry).where(LogEntry.skill_id == "skill_003")
            ).scalar_one()
            
            assert result3.payload == complex_payload, "Payload serialization failed"
            assert isinstance(result3.created_at, datetime), "created_at should be datetime"
            
        finally:
            session.close()
            engine.dispose()
    
    # Cleanup global state
    global _session_factory
    _session_factory = None
    
    print("_selftest passed")


if __name__ == "__main__":
    _selftest()
