"""
task_queue — Manage a queue of tasks that can be claimed by agents for execution. This module provides a centralized, scalable, and type-safe interface for task lifecycle management.

### PART-META-JSON
{
  "name": "task_queue",
  "layer": "agents",
  "purpose": "Manage a queue of tasks that can be claimed by agents for execution. This module provides a centralized, scalable, and type-safe interface for task lifecycle management.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "queen_worker_dispatch"
  ],
  "inputs": "Public API: Task(...); TaskQueue(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.task_queue`.",
  "example": "from scrapyard.agents.task_queue import *",
  "import_path": "scrapyard.agents.task_queue"
}
### END-PART-META
"""

"""
PURPOSE
Manage a queue of tasks that can be claimed by agents for execution. This module provides a centralized, scalable, and type-safe interface for task lifecycle management.

FEATURES
- TaskQueue class with thread-safe claim and complete operations.
- SQLAlchemy 2.x ORM models with Mapped attributes and proper table definitions.
- Full type hints and no runtime exceptions from missing imports.
- Self-contained module with no external dependencies at import time.
- _selftest() runs offline with temporary SQLite, proving core functionality.
- Uses select() queries and session.add() for database operations.
- Supports task claiming, completion, and state tracking.
- Integrates cleanly with queen_worker_dispatch for worker coordination.
- Logging used instead of print, with no bare except clauses.

PUBLIC API
class TaskQueue
def claim_task(worker_id: str) -> Optional[Task]
def complete_task(task_id: int, status: str) -> bool

TABLES
tasks: stores task metadata, status, and ownership.

SELFTEST MUST PROVE
- TaskQueue can be initialized and queried.
- claim_task() returns a task and marks it as claimed.
- complete_task() updates task status and releases it.
- Tasks are properly persisted to a temporary SQLite database.
- No exceptions raised during selftest execution.
- All type hints are respected and no type errors occur.
- Logging is used instead of print statements.
- No network or external dependencies are used during selftest.
"""

import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, select, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class Task(IntPKModel):
    """Represents a task in the queue."""
    __tablename__ = "task_queue_tasks"
    
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="Untitled")
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    worker_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    result_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


class TaskQueue:
    """Manages a queue of tasks for agent execution."""
    
    def __init__(self, connection_string: Optional[str] = None, engine: Optional[Engine] = None):
        """Initialize the task queue.
        
        Args:
            connection_string: Database connection string. Defaults to SQLite in current dir.
            engine: Optional pre-configured SQLAlchemy engine.
        """
        if engine:
            self.engine = engine
        else:
            conn_str = connection_string or "sqlite:///task_queue.db"
            self.engine = create_engine(conn_str, echo=False, future=True)
        
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
    
    def claim_task(self, worker_id: str) -> Optional[Task]:
        """Claim a pending task for execution by a worker.
        
        Args:
            worker_id: Unique identifier for the claiming worker.
            
        Returns:
            The claimed Task if available, None otherwise.
        """
        try:
            with self.Session() as session:
                stmt = (
                    select(Task)
                    .where(Task.status == "pending")
                    .limit(1)
                    .with_for_update()
                )
                task = session.execute(stmt).scalar_one_or_none()
                
                if task is None:
                    return None
                
                task.status = "claimed"
                task.worker_id = worker_id
                task.claimed_at = datetime.now(timezone.utc)
                
                session.commit()
                return task
                
        except Exception:
            logger.exception("Error claiming task for worker %s", worker_id)
            return None
    
    def complete_task(self, task_id: int, status: str) -> bool:
        """Mark a claimed task as completed.
        
        Args:
            task_id: ID of the task to complete.
            status: Completion status (e.g., 'success', 'failed').
            
        Returns:
            True if task was found and updated, False otherwise.
        """
        try:
            with self.Session() as session:
                stmt = (
                    select(Task)
                    .where(Task.id == task_id)
                    .where(Task.status == "claimed")
                )
                task = session.execute(stmt).scalar_one_or_none()
                
                if task is None:
                    return False
                
                task.status = "completed"
                task.result_status = status
                task.completed_at = datetime.now(timezone.utc)
                task.worker_id = None
                
                session.commit()
                return True
                
        except Exception:
            logger.exception("Error completing task %d", task_id)
            return False
    
    def add_task(self, title: str) -> Task:
        """Add a new task to the queue (convenience method for testing).
        
        Args:
            title: Title/description of the task.
            
        Returns:
            The created Task.
        """
        with self.Session() as session:
            task = Task(title=title, status="pending")
            session.add(task)
            session.commit()
            session.refresh(task)
            return task


def _selftest() -> bool:
    """Run offline self-test with temporary SQLite database.
    
    Returns:
        True if all tests pass.
    """
    logger.info("Starting task_queue selftest")
    engine = None
    
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = os.path.join(tmpdir, "test_task_queue.db")
            connection_string = f"sqlite:///{db_path}"
            
            engine = create_engine(connection_string, echo=False, future=True)
            Task.metadata.create_all(engine)
            
            queue = TaskQueue(engine=engine)
            
            task = queue.add_task("Test task 1")
            assert task.id is not None, "Task should have ID after creation"
            assert task.status == "pending", "Task should start as pending"
            assert isinstance(task, Task), "Should return Task type"
            
            claimed = queue.claim_task("worker-001")
            assert claimed is not None, "Should claim available task"
            assert claimed.status == "claimed", "Status should be 'claimed'"
            assert claimed.worker_id == "worker-001", "Worker ID should match"
            assert claimed.claimed_at is not None, "Should have claim timestamp"
            
            second_claim = queue.claim_task("worker-002")
            assert second_claim is None, "Should not claim already claimed task"
            
            result = queue.complete_task(claimed.id, "success")
            assert result is True, "Should complete successfully"
            
            verify_session = sessionmaker(bind=engine, expire_on_commit=False)
            with verify_session() as session:
                completed = session.get(Task, claimed.id)
                assert completed is not None, "Task should exist"
                assert completed.status == "completed", "Status should be 'completed'"
                assert completed.result_status == "success", "Result status should match"
                assert completed.worker_id is None, "Worker should be released"
                assert completed.completed_at is not None, "Should have completion timestamp"
            
            fail_result = queue.complete_task(99999, "fail")
            assert fail_result is False, "Should return False for non-existent task"
            
            task2 = queue.add_task("Task 2")
            task3 = queue.add_task("Task 3")
            
            claimed2 = queue.claim_task("worker-003")
            assert claimed2 is not None, "Should claim next pending task"
            assert claimed2.id == task2.id, "Should claim oldest pending task"
            
            claimed3 = queue.claim_task("worker-004")
            assert claimed3 is not None
            assert claimed3.id == task3.id
            
            no_more = queue.claim_task("worker-005")
            assert no_more is None, "Should return None when no pending tasks remain"
            
        logger.info("task_queue selftest passed")
        return True
        
    except Exception:
        logger.exception("task_queue selftest failed")
        return False
    finally:
        if engine:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
