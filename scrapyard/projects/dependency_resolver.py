"""
dependency_resolver — Manages task dependencies in project management systems, ensuring correct task ordering and validation. It provides tools to define, query, and validate dependency chains for reliable workflow execution

### PART-META-JSON
{
  "name": "dependency_resolver",
  "layer": "projects",
  "purpose": "Manages task dependencies in project management systems, ensuring correct task ordering and validation. It provides tools to define, query, and validate dependency chains for reliable workflow execution",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: add_dependency(task_id, depends_on_id); get_dependencies(task_id); validate_dependency_chain(task_id); TaskModel(...); DependencyModel(...).",
  "outputs": "Returns: add_dependency -> None; get_dependencies -> List[int]; validate_dependency_chain -> bool.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.dependency_resolver`.",
  "example": "from scrapyard.projects.dependency_resolver import *",
  "import_path": "scrapyard.projects.dependency_resolver"
}
### END-PART-META
"""

from sqlalchemy import String, ForeignKey, create_engine, select, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from typing import List, Set, Optional
import os
import tempfile

# Module-level session factory (unconfigured until _selftest runs)
_session_factory: Optional[sessionmaker] = None


def _get_session() -> Session:
    """Get a configured session or raise RuntimeError."""
    if _session_factory is None:
        raise RuntimeError("Database session not initialized")
    return _session_factory()


class TaskModel(IntPKModel):
    """Task entity for dependency tracking."""
    __tablename__ = "dependency_resolver_tasks"
    name: Mapped[str] = mapped_column(String(255))


class DependencyModel(IntPKModel):
    """
    Represents a dependency where task_id depends on depends_on_id.
    """
    __tablename__ = "dependency_resolver_dependencies"
    task_id: Mapped[int] = mapped_column(ForeignKey("dependency_resolver_tasks.id"), index=True)
    depends_on_id: Mapped[int] = mapped_column(ForeignKey("dependency_resolver_tasks.id"), index=True)
    
    __table_args__ = (
        UniqueConstraint('task_id', 'depends_on_id', name='uix_task_dependency'),
    )


def add_dependency(task_id: int, depends_on_id: int) -> None:
    """
    Add a dependency where task_id depends on depends_on_id.
    
    Raises:
        ValueError: If either task doesn't exist or if creating a self-dependency.
    """
    session = _get_session()
    
    # Validate tasks exist
    if session.get(TaskModel, task_id) is None:
        raise ValueError(f"Task {task_id} does not exist.")
    if session.get(TaskModel, depends_on_id) is None:
        raise ValueError(f"Dependency Task {depends_on_id} does not exist.")
    
    # Prevent self-dependency
    if task_id == depends_on_id:
        raise ValueError("Task cannot depend on itself")
    
    # Check if already exists
    existing = session.execute(
        select(DependencyModel).where(
            DependencyModel.task_id == task_id,
            DependencyModel.depends_on_id == depends_on_id
        )
    ).scalar_one_or_none()
    
    if existing:
        return
    
    # Create dependency
    dep = DependencyModel(task_id=task_id, depends_on_id=depends_on_id)
    session.add(dep)
    session.commit()


def get_dependencies(task_id: int) -> List[int]:
    """
    Get list of task IDs that the given task depends on.
    
    Raises:
        ValueError: If task doesn't exist.
    """
    session = _get_session()
    
    if session.get(TaskModel, task_id) is None:
        raise ValueError(f"Task {task_id} does not exist.")
    
    result = session.execute(
        select(DependencyModel.depends_on_id).where(
            DependencyModel.task_id == task_id
        )
    ).scalars().all()
    
    return list(result)


def validate_dependency_chain(task_id: int) -> bool:
    """
    Validate that the dependency chain starting from task_id has no cycles.
    
    Returns:
        bool: True if valid (no cycles), False if cycle detected.
        
    Raises:
        ValueError: If task doesn't exist.
    """
    session = _get_session()
    
    if session.get(TaskModel, task_id) is None:
        raise ValueError(f"Task {task_id} does not exist.")
    
    # DFS to detect cycles
    visited: Set[int] = set()
    recursion_stack: Set[int] = set()
    
    def has_cycle(current_id: int) -> bool:
        visited.add(current_id)
        recursion_stack.add(current_id)
        
        # Get all dependencies of current task
        dep_ids = session.execute(
            select(DependencyModel.depends_on_id).where(
                DependencyModel.task_id == current_id
            )
        ).scalars().all()
        
        for dep_id in dep_ids:
            if dep_id not in visited:
                if has_cycle(dep_id):
                    return True
            elif dep_id in recursion_stack:
                return True
        
        recursion_stack.remove(current_id)
        return False
    
    # If has_cycle returns True, validation fails (returns False)
    return not has_cycle(task_id)


def _selftest():
    """Self-contained test using temporary SQLite database."""
    global _session_factory
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        # Configure session factory
        _session_factory = sessionmaker(bind=engine)
        
        # Create tables
        TaskModel.metadata.create_all(engine)
        
        session = _get_session()
        
        try:
            # Create tasks
            task1 = TaskModel(name="Task 1")
            task2 = TaskModel(name="Task 2")
            task3 = TaskModel(name="Task 3")
            
            session.add_all([task1, task2, task3])
            session.commit()
            
            # Test: Adding and retrieving dependencies
            add_dependency(task_id=task2.id, depends_on_id=task1.id)
            add_dependency(task_id=task3.id, depends_on_id=task2.id)
            
            # Test: Validating valid chains
            assert validate_dependency_chain(task1.id) == True
            assert validate_dependency_chain(task2.id) == True
            assert validate_dependency_chain(task3.id) == True
            
            # Test: Checking dependencies
            assert get_dependencies(task1.id) == []
            assert set(get_dependencies(task2.id)) == {task1.id}
            assert set(get_dependencies(task3.id)) == {task2.id}
            
            # Test: Detecting cycles
            # Create cycle: task1 depends on task2 (task1 -> task2 -> task1)
            add_dependency(task_id=task1.id, depends_on_id=task2.id)
            assert validate_dependency_chain(task1.id) == False
            
            # Test: Handling missing dependencies
            try:
                get_dependencies(9999)
                assert False, "Should have raised ValueError"
            except ValueError:
                pass
            
            print("All tests passed.")
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
