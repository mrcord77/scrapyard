"""
task_manager — Manages task lifecycle and assignments for project workflows. Provides structured access to task data and ownership tracking.

### PART-META-JSON
{
  "name": "task_manager",
  "layer": "projects",
  "purpose": "Manages task lifecycle and assignments for project workflows. CANONICAL OWNER of the projects-layer Tasks, Projects and Users models (tables task_manager_tasks/_projects/_users): report_generator and other projects parts import these instead of defining duplicates.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model"],
  "inputs": "Task titles, project/owner/user ids; a Session factory bound by the application (or _selftest).",
  "outputs": "Frozen Task/TaskAssignment dataclasses mirroring the persisted rows.",
  "files_created": [],
  "security_notes": "No authorization checks: any caller can create, assign or complete any task, so enforce project membership/role checks in the calling layer. Each public function opens its own session and commits immediately (no caller-controlled transaction boundary).",
  "ai_usage": "Import what you need from `scrapyard.projects.task_manager`.",
  "example": "from scrapyard.projects.task_manager import *",
  "import_path": "scrapyard.projects.task_manager"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, func, ForeignKey, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker, synonym
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional
import logging

# Setup logger
logger = logging.getLogger(__name__)

# Session factory - unbound initially, configured by application or _selftest
Session = sessionmaker()

@dataclass(frozen=True)
class Task:
    id: int
    title: str
    project_id: int
    owner_id: int
    status: str
    created_at: datetime

@dataclass(frozen=True)
class TaskAssignment:
    id: int
    task_id: int
    user_id: int
    assigned_at: datetime

class Projects(IntPKModel):
    """Canonical project model for the projects layer (owned by task_manager).

    ``name`` is a synonym for ``title`` so both naming conventions used by
    consumer parts (e.g. report_generator) keep working.
    """
    __tablename__ = 'task_manager_projects'
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default='active', nullable=False)

    name = synonym('title')


class Users(IntPKModel):
    """Canonical lightweight user reference for the projects layer."""
    __tablename__ = 'task_manager_users'
    username: Mapped[str] = mapped_column(String(255), nullable=False)


class Tasks(IntPKModel):
    """Canonical task model for the projects layer (owned by task_manager)."""
    __tablename__ = 'task_manager_tasks'
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey('task_manager_projects.id'), nullable=False)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey('task_manager_users.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default='pending', nullable=False)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class TaskAssignments(IntPKModel):
    __tablename__ = 'task_assignments'
    task_id: Mapped[int] = mapped_column(ForeignKey('task_manager_tasks.id'), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey('task_manager_users.id'), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

def create_task(title: str, project_id: int, owner_id: int) -> Task:
    with Session() as session:
        task = Tasks(title=title, project_id=project_id, owner_id=owner_id)
        session.add(task)
        session.commit()
        session.refresh(task)
        return Task(
            id=task.id, 
            title=task.title, 
            project_id=task.project_id, 
            owner_id=task.owner_id, 
            status=task.status, 
            created_at=task.created_at
        )

def assign_task(task_id: int, user_id: int) -> TaskAssignment:
    with Session() as session:
        task_assignment = TaskAssignments(task_id=task_id, user_id=user_id)
        session.add(task_assignment)
        session.commit()
        session.refresh(task_assignment)
        return TaskAssignment(
            id=task_assignment.id, 
            task_id=task_assignment.task_id, 
            user_id=task_assignment.user_id, 
            assigned_at=task_assignment.assigned_at
        )

def complete_task(task_id: int) -> None:
    with Session() as session:
        task = session.get(Tasks, task_id)
        if task is not None and task.status != 'completed':
            task.status = 'completed'
            session.commit()
            logger.info(f"Task {task_id} marked as completed")
        elif task is None:
            logger.warning(f"Task {task_id} not found for completion")

def get_tasks_by_project(project_id: int) -> List[Task]:
    with Session() as session:
        stmt = select(Tasks).where(Tasks.project_id == project_id)
        tasks = session.execute(stmt).scalars().all()
        return [
            Task(
                id=t.id, 
                title=t.title, 
                project_id=t.project_id, 
                owner_id=t.owner_id, 
                status=t.status, 
                created_at=t.created_at
            ) for t in tasks
        ]

def _selftest():
    import tempfile
    import os
    from sqlalchemy import create_engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, 'test.db')
        engine = create_engine(f'sqlite:///{db_path}')
        
        global Session
        Session.configure(bind=engine)

        IntPKModel.metadata.create_all(engine)
        
        try:
            with Session() as session:
                project = Projects(title='Test Project')
                user = Users(username='admin')
                session.add_all([project, user])
                session.commit()
                
                task = create_task('Test Task', project.id, user.id)
                assert isinstance(task, Task)
                assert task.status == 'pending'
                
                assignment = assign_task(task.id, user.id)
                assert isinstance(assignment, TaskAssignment)
                assert assignment.task_id == task.id
                
                complete_task(task.id)
                
                tasks = get_tasks_by_project(project.id)
                assert len(tasks) == 1
                assert tasks[0].status == 'completed'
                assert tasks[0].title == 'Test Task'
                
            logger.info("Self-test passed successfully.")
        finally:
            engine.dispose()

if __name__ == "__main__":
    _selftest()
