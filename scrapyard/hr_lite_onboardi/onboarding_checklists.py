"""Onboarding checklists module for scrapyard.

Tracks and manages onboarding tasks for new employees, ensuring structured
and efficient employee integration.

### PART-META-JSON
{
  "name": "onboarding_checklists",
  "layer": "hr_lite_onboardi",
  "purpose": "Tracks and manages onboarding checklists and their tasks for new employees: checklist creation, task addition/completion, and progress queries.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model"],
  "inputs": "Checklist/task names and ids; a session factory bound via configure().",
  "outputs": "OnboardingChecklist and OnboardingTask rows; completion status and progress data.",
  "files_created": [],
  "security_notes": "No authorization checks: any caller can view or mutate any employee's checklist, so scope access in the calling layer. Task names/notes are stored verbatim - escape on render if displayed in HTML.",
  "ai_usage": "Call configure(session_factory), then use the checklist/task functions.",
  "example": "from scrapyard.hr_lite_onboardi.onboarding_checklists import configure",
  "import_path": "scrapyard.hr_lite_onboardi.onboarding_checklists"
}
### END-PART-META
"""
import logging
import os
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from typing import List, Optional, Callable

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, sessionmaker

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# Module-level session factory for dependency injection
_session_factory: Optional[Callable[[], Session]] = None


def configure(session_factory: Callable[[], Session]) -> None:
    """Configure the module with a session factory."""
    global _session_factory
    _session_factory = session_factory


def _get_session() -> Session:
    """Get the current session from the configured factory."""
    if _session_factory is None:
        raise RuntimeError("Module not configured. Call configure() first.")
    return _session_factory()


class OnboardingChecklist(IntPKModel):
    """Links tasks to employees."""
    
    __tablename__ = "onboarding_checklists"
    
    staff_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc)
    )
    
    tasks: Mapped[List["OnboardingTask"]] = relationship(
        "OnboardingTask", 
        back_populates="checklist",
        cascade="all, delete-orphan",
        lazy="selectin"
    )


class OnboardingTask(IntPKModel):
    """Stores task details and status."""
    
    __tablename__ = "onboarding_tasks"
    
    checklist_id: Mapped[int] = mapped_column(
        ForeignKey("onboarding_checklists.id"), 
        nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    checklist: Mapped["OnboardingChecklist"] = relationship(
        "OnboardingChecklist", 
        back_populates="tasks"
    )


def generate_checklist(staff_id: int) -> List[OnboardingTask]:
    """Generate a personalized onboarding checklist for a new employee.
    
    Args:
        staff_id: The ID of the staff member
        
    Returns:
        List of created onboarding tasks
    """
    session = _get_session()
    
    # Create checklist container
    checklist = OnboardingChecklist(staff_id=staff_id)
    session.add(checklist)
    session.flush()  # Get ID without committing transaction
    
    # Define default onboarding tasks
    task_definitions = [
        {
            "title": "Complete HR paperwork",
            "description": "Fill out tax forms, benefits enrollment, and emergency contacts"
        },
        {
            "title": "IT setup and access",
            "description": "Receive laptop, create accounts, and configure security"
        },
        {
            "title": "Security briefing",
            "description": "Review information security policies and sign NDA"
        },
        {
            "title": "Team introduction",
            "description": "Meet immediate team members and assigned buddy"
        },
        {
            "title": "Workspace orientation",
            "description": "Tour of facilities, parking, and amenities"
        }
    ]
    
    tasks: List[OnboardingTask] = []
    for task_def in task_definitions:
        task = OnboardingTask(
            checklist_id=checklist.id,
            title=task_def["title"],
            description=task_def["description"],
            is_completed=False,
            completed_at=None
        )
        session.add(task)
        tasks.append(task)
    
    session.flush()  # Persist tasks without committing
    return tasks


def mark_task_complete(task_id: int) -> None:
    """Mark a specific onboarding task as complete.
    
    Args:
        task_id: The ID of the task to mark complete
        
    Raises:
        ValueError: If task is not found
    """
    session = _get_session()
    
    stmt = select(OnboardingTask).where(OnboardingTask.id == task_id)
    task = session.execute(stmt).scalar_one_or_none()
    
    if task is None:
        raise ValueError(f"Task with id {task_id} not found")
    
    task.is_completed = True
    task.completed_at = datetime.now(timezone.utc)
    session.flush()  # Update state without committing


def _selftest() -> None:
    """Offline unit tests using temporary SQLite database."""
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_onboarding.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        
        # Configure session factory for this test
        Session = sessionmaker(bind=engine)
        test_session = Session()
        configure(lambda: test_session)
        
        try:
            # Test 1: Checklist generation for new staff member
            staff_id = 42
            tasks = generate_checklist(staff_id)
            
            assert isinstance(tasks, list), "Should return a list"
            assert len(tasks) == 5, "Should create 5 default tasks"
            assert all(isinstance(t, OnboardingTask) for t in tasks), "All items should be OnboardingTask instances"
            assert all(t.id is not None for t in tasks), "All tasks should have IDs after flush"
            assert all(t.checklist_id is not None for t in tasks), "All tasks should be linked to a checklist"
            
            # Verify checklist exists via ORM query
            checklist_id = tasks[0].checklist_id
            stmt = select(OnboardingChecklist).where(OnboardingChecklist.id == checklist_id)
            checklist = test_session.execute(stmt).scalar_one()
            assert checklist.staff_id == staff_id, "Checklist should be linked to correct staff"
            
            # Test 2: Task marking as complete and state update
            first_task_id = tasks[0].id
            assert tasks[0].is_completed is False, "Task should start incomplete"
            assert tasks[0].completed_at is None, "Task should have no completion time initially"
            
            mark_task_complete(first_task_id)
            
            # Verify state update via fresh query
            stmt = select(OnboardingTask).where(OnboardingTask.id == first_task_id)
            updated_task = test_session.execute(stmt).scalar_one()
            assert updated_task.is_completed is True, "Task should be marked complete"
            assert updated_task.completed_at is not None, "Task should have completion timestamp"
            
            # Test 3: Verify other tasks unaffected
            stmt = select(OnboardingTask).where(OnboardingTask.id == tasks[1].id)
            other_task = test_session.execute(stmt).scalar_one()
            assert other_task.is_completed is False, "Other tasks should remain incomplete"
            
            # Test 4: ORM relationship navigation
            stmt = select(OnboardingChecklist).where(OnboardingChecklist.staff_id == staff_id)
            fetched_checklist = test_session.execute(stmt).scalar_one()
            assert len(fetched_checklist.tasks) == 5, "Checklist should have 5 tasks via relationship"
            
            # Test 5: Select query validation
            stmt = select(OnboardingTask).join(OnboardingChecklist).where(
                OnboardingChecklist.staff_id == staff_id,
                OnboardingTask.is_completed == True
            )
            completed_tasks = test_session.execute(stmt).scalars().all()
            assert len(completed_tasks) == 1, "Should find exactly one completed task"
            
        finally:
            test_session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
