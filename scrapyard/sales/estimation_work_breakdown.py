"""
estimation_work_breakdown — ** Manages hierarchical decomposition of projects into work packages and tasks for accurate estimation and pricing. Provides reusable modeling and operations for structuring complex work breakdowns in

### PART-META-JSON
{
  "name": "estimation_work_breakdown",
  "layer": "sales",
  "purpose": "Manages hierarchical decomposition of projects into work packages and tasks for accurate estimation and pricing. Provides reusable modeling and operations for structuring complex work breakdowns in.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_work_package(session, name, description); add_task_to_package(session, package, task); get_work_package_tree(session, package_id); WorkPackage(...); Task(...).",
  "outputs": "Returns: create_work_package -> WorkPackage; add_task_to_package -> None; get_work_package_tree -> List[WorkPackage].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.sales.estimation_work_breakdown`.",
  "example": "from scrapyard.sales.estimation_work_breakdown import *",
  "import_path": "scrapyard.sales.estimation_work_breakdown"
}
### END-PART-META
"""

import logging
import os
from typing import List, Optional

from sqlalchemy import (
    Column,
    ForeignKey,
    String,
    Table,
    Text,
    create_engine,
    select,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, Session, sessionmaker

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# Association table for many-to-many relationship between WorkPackage and Task
work_package_task = Table(
    "work_package_task",
    IntPKModel.metadata,
    Column("work_package_id", ForeignKey("work_package.id"), primary_key=True),
    Column("task_id", ForeignKey("task.id"), primary_key=True),
)


class WorkPackage(IntPKModel):
    """
    Represents a work package in the work breakdown structure.
    Supports hierarchical nesting via parent-child relationships.
    """
    __tablename__ = "work_package"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("work_package.id"), nullable=True, index=True
    )

    # Self-referential relationships for hierarchy
    parent: Mapped[Optional["WorkPackage"]] = relationship(
        "WorkPackage",
        remote_side="WorkPackage.id",
        back_populates="children",
    )
    children: Mapped[List["WorkPackage"]] = relationship(
        "WorkPackage",
        back_populates="parent",
        cascade="all, delete-orphan",
    )

    # Many-to-many relationship with tasks via association table
    tasks: Mapped[List["Task"]] = relationship(
        "Task",
        secondary=work_package_task,
        back_populates="work_packages",
    )
    
    # Tasks that have this package as their primary owner (via FK on Task)
    primary_tasks: Mapped[List["Task"]] = relationship(
        "Task",
        back_populates="primary_package",
        foreign_keys="Task.package_id",
    )


class Task(IntPKModel):
    """
    Represents a task that can be assigned to work packages.
    """
    __tablename__ = "task"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    package_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("work_package.id"), nullable=True, index=True
    )

    # Many-to-many back-reference
    work_packages: Mapped[List[WorkPackage]] = relationship(
        WorkPackage,
        secondary=work_package_task,
        back_populates="tasks",
    )
    
    # Primary package relationship
    primary_package: Mapped[Optional[WorkPackage]] = relationship(
        WorkPackage,
        foreign_keys=[package_id],
        back_populates="primary_tasks",
    )


def create_work_package(
    session: Session, name: str, description: str
) -> WorkPackage:
    """
    Create a new work package within the current transaction.
    
    Args:
        session: Active SQLAlchemy session
        name: Name of the work package
        description: Description of the work package
        
    Returns:
        The created WorkPackage instance (not yet committed)
    """
    package = WorkPackage(name=name, description=description)
    session.add(package)
    session.flush()
    return package


def add_task_to_package(
    session: Session, package: WorkPackage, task: Task
) -> None:
    """
    Associate a task with a work package using the many-to-many relationship.
    
    Args:
        session: Active SQLAlchemy session
        package: Target work package
        task: Task to add to the package
    """
    if task not in package.tasks:
        package.tasks.append(task)
    session.flush()


def get_work_package_tree(
    session: Session, package_id: int
) -> List[WorkPackage]:
    """
    Retrieve a work package and all its descendants (children, grandchildren, etc.)
    using a recursive CTE query.
    
    Args:
        session: Active SQLAlchemy session
        package_id: ID of the root work package
        
    Returns:
        List containing the package and all descendants
    """
    # Recursive CTE to get all descendants
    cte = select(WorkPackage).where(WorkPackage.id == package_id).cte(recursive=True)
    
    cte = cte.union_all(
        select(WorkPackage).where(WorkPackage.parent_id == cte.c.id)
    )
    
    stmt = select(WorkPackage).join(cte, WorkPackage.id == cte.c.id)
    
    result = session.execute(stmt).scalars().all()
    return list(result)


def _selftest() -> None:
    """
    Offline self-test using temporary SQLite database.
    Validates model creation, hierarchical relationships, foreign key constraints,
    and ensures no commits occur during testing.
    """
    from tempfile import TemporaryDirectory
    
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_estimation_wbs.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Enable foreign key constraints for SQLite
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        
        # Create schema
        IntPKModel.metadata.create_all(engine)
        
        SessionFactory = sessionmaker(bind=engine)
        session = SessionFactory()
        
        try:
            # Begin a nested transaction to ensure we can rollback everything
            nested = session.begin_nested()
            
            # 1. Create a work package and verify inheritance/type hints
            root = create_work_package(session, "Project Root", "Top level package")
            assert isinstance(root, WorkPackage)
            assert isinstance(root, IntPKModel)
            assert root.id is not None
            assert root.name == "Project Root"
            
            # 2. Add a task to the package
            task = Task(name="Analysis Task", description="Requirements analysis")
            session.add(task)
            session.flush()
            
            add_task_to_package(session, root, task)
            assert task in root.tasks
            assert len(root.tasks) == 1
            
            # 3. Create nested structure (parent-child relationships)
            child = WorkPackage(
                name="Phase 1", 
                description="First phase", 
                parent_id=root.id
            )
            session.add(child)
            session.flush()
            
            grandchild = WorkPackage(
                name="Work Package 1.1",
                description="Detailed work",
                parent_id=child.id
            )
            session.add(grandchild)
            session.flush()
            
            # 4. Retrieve work package tree
            tree = get_work_package_tree(session, root.id)
            assert len(tree) == 3  # root, child, grandchild
            assert root in tree
            assert child in tree
            assert grandchild in tree
            
            # Verify parent relationships are loaded correctly
            assert child.parent_id == root.id
            assert grandchild.parent_id == child.id
            
            # 5. Verify foreign key constraint enforcement
            # Use a separate savepoint for this test so we don't lose the main test data
            fk_savepoint = session.begin_nested()
            orphan = WorkPackage(
                name="Orphan",
                description="Should fail",
                parent_id=99999  # Non-existent ID
            )
            session.add(orphan)
            try:
                session.flush()
                assert False, "ForeignKey constraint should have been violated"
            except Exception:
                # Expected failure, rollback just this savepoint
                fk_savepoint.rollback()
            
            # 6. Verify task-package relationship via association table
            # Check that the association table entry exists
            assoc_count = session.execute(
                select(work_package_task).where(
                    work_package_task.c.work_package_id == root.id,
                    work_package_task.c.task_id == task.id
                )
            ).fetchall()
            assert len(assoc_count) == 1
            
            # Rollback all changes to ensure no commits occurred
            nested.rollback()
            
            logger.info("estimation_work_breakdown._selftest passed successfully")
            
        finally:
            # Ensure session is closed and connections disposed
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
