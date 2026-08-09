"""
milestone_tracker — Tracks milestones and their relationship to projects, enabling structured project progress monitoring. Provides a reusable, scalable interface for managing milestones with SQLAlchemy and type-safe mapped columns.

### PART-META-JSON
{
  "name": "milestone_tracker",
  "layer": "projects",
  "purpose": "Tracks milestones and their relationship to projects, enabling structured project progress monitoring. CANONICAL OWNER of the projects-layer Milestone and ProjectMilestone models (tables milestone_tracker_milestones / project_milestones): report_generator and other parts import these instead of defining duplicates.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model"],
  "inputs": "SQLAlchemy Session, project ids, milestone names and due-date datetimes.",
  "outputs": "Milestone ORM instances and lists of milestones per project; ValueError for missing milestones.",
  "files_created": [],
  "security_notes": "No authorization checks: callers must verify the acting user may read or modify milestones for the given project. add_milestone and update_milestone_date commit on the caller's session immediately.",
  "ai_usage": "Import what you need from `scrapyard.projects.milestone_tracker`.",
  "example": "from scrapyard.projects.milestone_tracker import *",
  "import_path": "scrapyard.projects.milestone_tracker"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from typing import List

from typing import Optional

from sqlalchemy import ForeignKey, String, DateTime, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship, synonym
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class ProjectMilestone(IntPKModel):
    """Link table associating milestones with projects."""
    __tablename__ = "project_milestones"
    
    milestone_id: Mapped[int] = mapped_column(ForeignKey("milestone_tracker_milestones.id"), nullable=False)
    project_id: Mapped[int] = mapped_column(nullable=False)
    
    milestone: Mapped[Milestone] = relationship(back_populates="project_links")


class Milestone(IntPKModel):
    """Represents a project milestone with a name and due date."""
    __tablename__ = "milestone_tracker_milestones"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    project_links: Mapped[List[ProjectMilestone]] = relationship(back_populates="milestone")

    # ``title`` synonym so consumers using the title naming convention compose.
    title = synonym("name")


def add_milestone(session: Session, project_id: int, name: str, due_date: datetime) -> Milestone:
    """Create a new milestone and link it to the specified project."""
    milestone = Milestone(name=name, due_date=due_date)
    session.add(milestone)
    session.flush()  # Obtain milestone.id
    
    link = ProjectMilestone(milestone_id=milestone.id, project_id=project_id)
    session.add(link)
    session.commit()
    return milestone


def update_milestone_date(session: Session, milestone_id: int, new_date: datetime) -> None:
    """Update the due date of an existing milestone."""
    milestone = session.get(Milestone, milestone_id)
    if milestone is None:
        raise ValueError(f"Milestone with id {milestone_id} not found")
    milestone.due_date = new_date
    session.commit()


def get_milestones_by_project(session: Session, project_id: int) -> list[Milestone]:
    """Retrieve all milestones associated with a given project."""
    stmt = (
        select(Milestone)
        .join(ProjectMilestone, Milestone.id == ProjectMilestone.milestone_id)
        .where(ProjectMilestone.project_id == project_id)
    )
    return list(session.scalars(stmt))


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = f"{tmpdir}/test.db"
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create schema
        IntPKModel.metadata.create_all(engine)
        
        with Session(engine) as session:
            # Test data - SQLite stores naive datetimes, so use naive datetimes for comparison
            project_id = 1
            due_date = datetime(2024, 12, 31, 23, 59, 59)
            
            # Test add_milestone
            milestone = add_milestone(session, project_id, "Launch v1.0", due_date)
            assert isinstance(milestone, Milestone)
            assert milestone.id is not None
            assert milestone.name == "Launch v1.0"
            assert milestone.due_date == due_date
            
            # Test get_milestones_by_project
            milestones = get_milestones_by_project(session, project_id)
            assert isinstance(milestones, list)
            assert len(milestones) == 1
            assert isinstance(milestones[0], Milestone)
            assert milestones[0].id == milestone.id
            
            # Test update_milestone_date
            new_date = datetime(2025, 1, 15, 12, 0, 0)
            update_milestone_date(session, milestone.id, new_date)
            
            # Verify update
            session.expire(milestone)
            updated = session.get(Milestone, milestone.id)
            assert updated.due_date == new_date
            
            # Test empty result for non-existent project
            empty = get_milestones_by_project(session, 999)
            assert empty == []
            
            # Test error on update non-existent milestone
            try:
                update_milestone_date(session, 9999, new_date)
                assert False, "Expected ValueError for missing milestone"
            except ValueError:
                pass
        
        engine.dispose()
        logger.info("_selftest passed successfully")


if __name__ == "__main__":
    _selftest()
