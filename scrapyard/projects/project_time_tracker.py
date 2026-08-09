"""
project_time_tracker — Tracks time spent on projects and tasks, enabling project-level time reporting. Provides structured logging and querying of time entries.

### PART-META-JSON
{
  "name": "project_time_tracker",
  "layer": "projects",
  "purpose": "Tracks time spent on projects and tasks, enabling project-level time reporting. Provides structured logging and querying of time entries.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure(engine); log_time_to_project(project_id, timer_id); get_project_time_summary(project_id); ProjectTimeEntry(...).",
  "outputs": "Returns: log_time_to_project -> None; get_project_time_summary -> dict[str, Any].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.project_time_tracker`.",
  "example": "from scrapyard.projects.project_time_tracker import *",
  "import_path": "scrapyard.projects.project_time_tracker"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

_engine = None


class ProjectTimeEntry(IntPKModel):
    __tablename__ = "project_time_entries"
    project_id: Mapped[str] = mapped_column(String(36))
    timer_id: Mapped[str] = mapped_column(String(36))
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


def configure(engine):
    """Configure the database engine for the module."""
    global _engine
    _engine = engine


def _get_session():
    """Get a database session."""
    if _engine is None:
        raise RuntimeError("Database not configured. Call configure() first.")
    return Session(_engine)


def log_time_to_project(project_id: str, timer_id: str) -> None:
    """Log a new time entry for a project."""
    session = _get_session()
    try:
        entry = ProjectTimeEntry(
            project_id=project_id,
            timer_id=timer_id,
            start_time=datetime.now(timezone.utc),
            end_time=None
        )
        session.add(entry)
        session.commit()
        logger.debug(f"Logged time entry for project {project_id}, timer {timer_id}")
    finally:
        session.close()


def get_project_time_summary(project_id: str) -> dict[str, Any]:
    """Get aggregated time summary for a project."""
    session = _get_session()
    try:
        stmt = select(ProjectTimeEntry).where(ProjectTimeEntry.project_id == project_id)
        entries = session.execute(stmt).scalars().all()
        
        total_duration = 0.0
        entry_list = []
        
        for entry in entries:
            entry_data = {
                "id": entry.id,
                "timer_id": entry.timer_id,
                "start_time": entry.start_time.isoformat() if entry.start_time else None,
                "end_time": entry.end_time.isoformat() if entry.end_time else None,
            }
            entry_list.append(entry_data)
            
            if entry.end_time and entry.start_time:
                duration = (entry.end_time - entry.start_time).total_seconds()
                total_duration += duration
        
        return {
            "project_id": project_id,
            "total_entries": len(entries),
            "total_duration_seconds": total_duration,
            "entries": entry_list
        }
    finally:
        session.close()


def _selftest():
    """Self-contained test for the module."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            # Create tables
            ProjectTimeEntry.metadata.create_all(engine)
            
            # Configure module
            configure(engine)
            
            # Test: Log time entries
            log_time_to_project("proj-abc", "timer-001")
            log_time_to_project("proj-abc", "timer-002")
            log_time_to_project("proj-xyz", "timer-003")
            
            # Test: Get summary for proj-abc
            summary_abc = get_project_time_summary("proj-abc")
            assert summary_abc["project_id"] == "proj-abc"
            assert summary_abc["total_entries"] == 2
            assert summary_abc["total_duration_seconds"] == 0.0  # No end times yet
            assert len(summary_abc["entries"]) == 2
            
            # Test: Verify entry structure and types
            entry = summary_abc["entries"][0]
            assert isinstance(entry["id"], int)
            assert isinstance(entry["timer_id"], str)
            assert isinstance(entry["start_time"], str)
            assert entry["end_time"] is None
            assert entry["timer_id"] in ["timer-001", "timer-002"]
            
            # Test: Add completed entry via ORM to validate model persistence
            session = Session(engine)
            completed_entry = ProjectTimeEntry(
                project_id="proj-abc",
                timer_id="timer-003",
                start_time=datetime.now(timezone.utc) - timedelta(hours=2),
                end_time=datetime.now(timezone.utc)
            )
            session.add(completed_entry)
            session.commit()
            session.close()
            
            # Test: Summary includes duration from completed entry
            summary_abc_2 = get_project_time_summary("proj-abc")
            assert summary_abc_2["total_entries"] == 3
            # Should have approximately 7200 seconds (2 hours) from the completed entry
            assert 7190 <= summary_abc_2["total_duration_seconds"] <= 7210
            
            # Test: Empty project returns zeroed summary
            summary_empty = get_project_time_summary("nonexistent-proj")
            assert summary_empty["project_id"] == "nonexistent-proj"
            assert summary_empty["total_entries"] == 0
            assert summary_empty["total_duration_seconds"] == 0.0
            assert summary_empty["entries"] == []
            
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
