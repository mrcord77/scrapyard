"""
timer_manager — Manages creation, start, pause, and stop of individual timers. Provides a reusable ORM model and API for time-tracking functionality in software products.

### PART-META-JSON
{
  "name": "timer_manager",
  "layer": "projects",
  "purpose": "Manages creation, start, pause, and stop of individual timers. Provides a reusable ORM model and API for time-tracking functionality in software products.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "scrapyard.database.base_model",
    "sqlalchemy.orm",
    "sqlite3"
  ],
  "inputs": "Public API: get_timer(session, timer_id); add_timer(session, timer_id); delete_timer(session, timer_id); start_timer(session, timer_id); pause_timer(session, timer_id); Timer(...) (plus more).",
  "outputs": "Returns: get_timer -> Optional[Timer]; add_timer -> Timer; delete_timer -> bool; start_timer -> None; pause_timer -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.timer_manager`.",
  "example": "from scrapyard.projects.timer_manager import *",
  "import_path": "scrapyard.projects.timer_manager"
}
### END-PART-META
"""

import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class Timer(IntPKModel):
    """ORM model for the timers table."""
    __tablename__ = "timers"

    timer_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="created")
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    pause_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    elapsed_paused: Mapped[float] = mapped_column(Float, default=0.0)


def get_timer(session: Session, timer_id: str) -> Optional[Timer]:
    """Retrieve a timer by its string identifier."""
    stmt = select(Timer).where(Timer.timer_id == timer_id)
    return session.execute(stmt).scalar_one_or_none()


def add_timer(session: Session, timer_id: str) -> Timer:
    """Create and add a new timer to the session."""
    timer = Timer(timer_id=timer_id, status="created")
    session.add(timer)
    logger.debug(f"Added timer {timer_id}")
    return timer


def delete_timer(session: Session, timer_id: str) -> bool:
    """Delete a timer from the session. Returns True if deleted, False if not found."""
    timer = get_timer(session, timer_id)
    if timer is None:
        return False
    session.delete(timer)
    logger.debug(f"Deleted timer {timer_id}")
    return True


def _ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware UTC. Handles naive datetimes from DB."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def start_timer(session: Session, timer_id: str) -> None:
    """
    Start or resume a timer.
    Creates the timer if it doesn't exist.
    """
    try:
        timer = get_timer(session, timer_id)
        now = datetime.now(timezone.utc)
        
        if timer is None:
            timer = Timer(timer_id=timer_id, status="running", start_time=now)
            session.add(timer)
            logger.info(f"Created and started timer {timer_id}")
            return
        
        if timer.status == "running":
            logger.warning(f"Timer {timer_id} is already running")
            return
        
        if timer.status == "paused":
            pause_time = _ensure_aware(timer.pause_time)
            if pause_time:
                paused_duration = (now - pause_time).total_seconds()
                timer.elapsed_paused += paused_duration
            timer.pause_time = None
            timer.status = "running"
            logger.info(f"Resumed timer {timer_id}")
            return
        
        if timer.status == "stopped":
            # Restart: reset all timing fields
            timer.start_time = now
            timer.end_time = None
            timer.pause_time = None
            timer.elapsed_paused = 0.0
            timer.status = "running"
            logger.info(f"Restarted timer {timer_id}")
            return
        
        if timer.status == "created":
            timer.start_time = now
            timer.status = "running"
            logger.info(f"Started timer {timer_id}")
            return
            
        raise ValueError(f"Unknown timer status: {timer.status}")
        
    except Exception as e:
        logger.error(f"Error starting timer {timer_id}: {e}")
        raise


def pause_timer(session: Session, timer_id: str) -> None:
    """Pause a running timer."""
    try:
        timer = get_timer(session, timer_id)
        if timer is None:
            raise ValueError(f"Timer {timer_id} not found")
        
        if timer.status != "running":
            raise ValueError(f"Cannot pause timer {timer_id} with status {timer.status}")
        
        timer.pause_time = datetime.now(timezone.utc)
        timer.status = "paused"
        logger.info(f"Paused timer {timer_id}")
        
    except Exception as e:
        logger.error(f"Error pausing timer {timer_id}: {e}")
        raise


def stop_timer(session: Session, timer_id: str) -> None:
    """Stop a running or paused timer."""
    try:
        timer = get_timer(session, timer_id)
        if timer is None:
            raise ValueError(f"Timer {timer_id} not found")
        
        if timer.status == "stopped":
            logger.warning(f"Timer {timer_id} is already stopped")
            return
        
        now = datetime.now(timezone.utc)
        
        if timer.status == "paused":
            # Account for final paused period
            pause_time = _ensure_aware(timer.pause_time)
            if pause_time:
                paused_duration = (now - pause_time).total_seconds()
                timer.elapsed_paused += paused_duration
            timer.pause_time = None
        
        if timer.status not in ("running", "paused"):
            raise ValueError(f"Cannot stop timer {timer_id} with status {timer.status}")
        
        timer.end_time = now
        timer.status = "stopped"
        logger.info(f"Stopped timer {timer_id}")
        
    except Exception as e:
        logger.error(f"Error stopping timer {timer_id}: {e}")
        raise


def _selftest() -> None:
    """Offline selftest using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        
        try:
            with Session(engine) as session:
                # Test add and get
                timer_id = "test-timer-1"
                add_timer(session, timer_id)
                session.commit()
                
                timer = get_timer(session, timer_id)
                assert timer is not None, "Timer should exist after add"
                assert timer.status == "created", "New timer should have status 'created'"
                
                # Test start
                start_timer(session, timer_id)
                session.commit()
                timer = get_timer(session, timer_id)
                assert timer.status == "running", "Timer should be running after start"
                assert timer.start_time is not None, "Timer should have start_time"
                
                # Test pause
                time.sleep(0.05)  # Small delay to ensure measurable time
                pause_timer(session, timer_id)
                session.commit()
                timer = get_timer(session, timer_id)
                assert timer.status == "paused", "Timer should be paused"
                assert timer.pause_time is not None, "Timer should have pause_time"
                
                # Test resume (start when paused)
                time.sleep(0.05)
                start_timer(session, timer_id)
                session.commit()
                timer = get_timer(session, timer_id)
                assert timer.status == "running", "Timer should be running after resume"
                assert timer.pause_time is None, "pause_time should be cleared after resume"
                assert timer.elapsed_paused > 0, "elapsed_paused should accumulate"
                
                # Test stop
                stop_timer(session, timer_id)
                session.commit()
                timer = get_timer(session, timer_id)
                assert timer.status == "stopped", "Timer should be stopped"
                assert timer.end_time is not None, "Timer should have end_time"
                
                # Test delete
                assert delete_timer(session, timer_id) is True, "Delete should return True"
                session.commit()
                assert get_timer(session, timer_id) is None, "Timer should not exist after delete"
                
                # Test invalid inputs
                try:
                    pause_timer(session, "non-existent-timer")
                    assert False, "Should raise ValueError for non-existent timer"
                except ValueError:
                    pass
                
                try:
                    stop_timer(session, "non-existent-timer")
                    assert False, "Should raise ValueError for non-existent timer"
                except ValueError:
                    pass
                
                # Test double start (idempotent/warning behavior)
                add_timer(session, "timer-2")
                session.commit()
                start_timer(session, "timer-2")
                session.commit()
                start_timer(session, "timer-2")  # Already running - should log warning
                session.commit()
                timer = get_timer(session, "timer-2")
                assert timer is not None, "Timer-2 should exist"
                assert timer.status == "running", "Timer-2 should still be running after double start"
                
                # Clean up timer-2
                stop_timer(session, "timer-2")
                session.commit()
                
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
