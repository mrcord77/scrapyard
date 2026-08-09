"""
action_tracer — Tracks the execution of each action for debugging and learning, providing a detailed audit trail of agent behavior. It enables post-hoc analysis and performance optimization by capturing start and end

### PART-META-JSON
{
  "name": "action_tracer",
  "layer": "agents",
  "purpose": "Tracks the execution of each action for debugging and learning, providing a detailed audit trail of agent behavior. It enables post-hoc analysis and performance optimization by capturing start and end",
  "addition": true,
  "status": "core",
  "dependencies": [
    "executor"
  ],
  "inputs": "Public API: start_trace(action); end_trace(action); Action(...); Trace(...).",
  "outputs": "Returns: start_trace -> None; end_trace -> None.",
  "files_created": [
    "traces"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.action_tracer`.",
  "example": "from scrapyard.agents.action_tracer import *",
  "import_path": "scrapyard.agents.action_tracer"
}
### END-PART-META
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol

from sqlalchemy import DateTime, Integer, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class Action(Protocol):
    """Protocol for objects that can be traced."""
    id: int


class Trace(IntPKModel):
    """Database model for action execution traces."""
    __tablename__ = "traces"
    
    action_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# Module-level session reference (configured by executor or tests)
_session: Optional[Session] = None


def _get_session() -> Session:
    """Retrieve the currently configured database session."""
    if _session is None:
        raise RuntimeError("action_tracer: no database session configured")
    return _session


def start_trace(action: Action) -> None:
    """Record the start of an action execution.
    
    Args:
        action: The action being traced. Must provide an `id` attribute.
    """
    session = _get_session()
    now = datetime.now(timezone.utc)
    trace = Trace(action_id=action.id, start_time=now, end_time=None)
    session.add(trace)
    session.commit()
    logger.debug(f"Started trace for action {action.id}")


def end_trace(action: Action) -> None:
    """Record the end of an action execution.
    
    Args:
        action: The action being traced. Must provide an `id` attribute.
    """
    session = _get_session()
    stmt = (
        select(Trace)
        .where(Trace.action_id == action.id)
        .where(Trace.end_time.is_(None))
        .order_by(Trace.start_time.desc())
    )
    trace = session.execute(stmt).scalars().first()
    
    if trace is None:
        logger.warning(f"No active trace found for action {action.id}")
        return
    
    trace.end_time = datetime.now(timezone.utc)
    session.commit()
    logger.debug(f"Ended trace for action {action.id}")


def _selftest() -> None:
    """Execute self-test with temporary SQLite database."""
    global _session
    original_session = _session
    
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            engine = create_engine(f"sqlite:///{db_path}")
            
            # Create tables
            IntPKModel.metadata.create_all(engine)
            
            with Session(engine) as session:
                _session = session
                
                @dataclass
                class MockAction:
                    id: int
                
                action = MockAction(id=999)
                
                # Test start_trace records correct timestamp
                start_trace(action)
                trace = session.execute(
                    select(Trace).where(Trace.action_id == 999)
                ).scalar_one()
                
                assert trace.start_time is not None
                assert trace.end_time is None
                start_ts = trace.start_time
                
                # Small delay to ensure measurable time difference
                time.sleep(0.01)
                
                # Test end_trace records correct timestamp
                end_trace(action)
                session.refresh(trace)
                
                assert trace.end_time is not None
                assert trace.end_time >= start_ts
                
                logger.info("action_tracer selftest passed")
    finally:
        _session = original_session


if __name__ == "__main__":
    _selftest()
