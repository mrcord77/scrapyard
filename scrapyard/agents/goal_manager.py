"""
goal_manager — Manages an agent's evolving set of goals, dynamically updating them based on progress and new information. Integrates with the planner to ensure goals remain actionable and aligned with the agent's mi

### PART-META-JSON
{
  "name": "goal_manager",
  "layer": "agents",
  "purpose": "Manages an agent's evolving set of goals, dynamically updating them based on progress and new information. Integrates with the planner to ensure goals remain actionable and aligned with the agent's mi",
  "addition": true,
  "status": "core",
  "dependencies": [
    "planner"
  ],
  "inputs": "Public API: configure(database_url, engine); is_configured(); get_engine(); reset_configuration(); session_scope(); Goal(...) (plus more).",
  "outputs": "Returns: configure -> None; is_configured -> bool; get_engine -> Optional[Engine]; reset_configuration -> None; session_scope -> Session.",
  "files_created": [
    "goals"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.goal_manager`.",
  "example": "from scrapyard.agents.goal_manager import *",
  "import_path": "scrapyard.agents.goal_manager"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, create_engine, Engine, select, func
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from typing import Dict, Any, Optional, List, Union
from contextlib import contextmanager
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

# Type aliases for clarity
GoalState = Dict[str, Dict[str, Any]]
GoalID = Union[int, str]

# Module-level configuration state
_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def configure(database_url: Optional[str] = None, engine: Optional[Engine] = None) -> None:
    """
    Configure the database connection for the goal manager module.
    
    This function must be called before using any database operations.
    It sets up the SQLAlchemy engine and session factory.
    
    Args:
        database_url: A SQLAlchemy database URL (e.g., 'sqlite:///path/to/db.sqlite')
        engine: A pre-configured SQLAlchemy Engine instance (takes precedence over database_url)
    
    Raises:
        ValueError: If neither database_url nor engine is provided
        RuntimeError: If configuration fails due to database connectivity issues
    
    Example:
        >>> configure(database_url="sqlite:///goals.db")
        >>> # or
        >>> engine = create_engine("postgresql://user:pass@localhost/db")
        >>> configure(engine=engine)
    """
    global _engine, _session_factory
    
    if engine is not None:
        _engine = engine
    elif database_url is not None:
        try:
            _engine = create_engine(database_url, echo=False, future=True)
        except Exception as e:
            raise RuntimeError(f"Failed to create database engine: {e}") from e
    else:
        raise ValueError("Either database_url or engine must be provided")
    
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    logger.debug("Goal manager configured with engine: %s", _engine.url)


def is_configured() -> bool:
    """
    Check if the goal manager has been configured with a database engine.
    
    Returns:
        True if configured, False otherwise
    """
    return _engine is not None and _session_factory is not None


def get_engine() -> Optional[Engine]:
    """
    Get the currently configured engine.
    
    Returns:
        The configured Engine instance or None if not configured
    """
    return _engine


def reset_configuration() -> None:
    """
    Reset the module configuration. Useful for testing.
    """
    global _engine, _session_factory
    _engine = None
    _session_factory = None
    logger.debug("Goal manager configuration reset")


@contextmanager
def session_scope() -> Session:
    """
    Provide a transactional scope around a series of operations.
    
    Automatically handles commit/rollback and session cleanup.
    Must only be used after configure() has been called.
    
    Yields:
        An active SQLAlchemy Session instance
    
    Raises:
        RuntimeError: If the module is not configured
        Exception: Re-raises any exception after rollback
    
    Example:
        >>> with session_scope() as session:
        ...     goal = session.get(Goal, 1)
        ...     goal.priority = 5
    """
    if _session_factory is None:
        raise RuntimeError(
            "Database not configured. Call configure() before using database operations."
        )
    
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("Session rollback due to error: %s", e)
        raise
    finally:
        session.close()


class Goal(IntPKModel):
    """
    Represents an agent's goal with priority and description.
    
    This model maps to the 'goals' table and provides the core data structure
    for tracking agent objectives. Goals are ordered by priority and can be
    dynamically updated based on agent state changes.
    
    Attributes:
        id: Primary key integer identifier
        description: Human-readable description of the goal (max 255 chars)
        priority: Integer priority level where lower numbers typically indicate
                 higher priority or urgency
    
    Table Name:
        goals
    """
    __tablename__ = 'goals'
    
    description: Mapped[str] = mapped_column(
        String(255), 
        nullable=False,
        index=True,
        comment="Description of the goal objective"
    )
    priority: Mapped[int] = mapped_column(
        Integer, 
        nullable=False, 
        default=0,
        index=True,
        comment="Priority level (lower typically means higher priority)"
    )
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"<Goal(id={self.id}, priority={self.priority}, "
            f"description='{self.description[:50]}...')>"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert goal to dictionary representation.
        
        Returns:
            Dictionary with id, description, and priority keys
        """
        return {
            "id": self.id,
            "description": self.description,
            "priority": self.priority
        }


def add_goal(goal: str, priority: int) -> None:
    """
    Add a new goal to the persistent database.
    
    Creates a new Goal record with the specified description and priority.
    The goal is immediately committed to the database.
    
    Args:
        goal: Description text for the goal (required, non-empty)
        priority: Integer priority value (required)
    
    Raises:
        RuntimeError: If the database has not been configured
        ValueError: If goal is empty or None, or if priority is not an integer
    
    Example:
        >>> configure(database_url="sqlite:///test.db")
        >>> add_goal("Repair hydraulic system", priority=1)
    """
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("Goal description must be a non-empty string")
    
    if not isinstance(priority, int):
        raise ValueError("Priority must be an integer")
    
    cleaned_goal = goal.strip()
    
    with session_scope() as session:
        new_goal = Goal(description=cleaned_goal, priority=priority)
        session.add(new_goal)
        logger.debug("Added new goal: %s with priority %d", cleaned_goal, priority)


def get_goal(goal_id: int) -> Optional[Goal]:
    """
    Retrieve a specific goal by its ID.
    
    Args:
        goal_id: The integer ID of the goal to retrieve
    
    Returns:
        The Goal object if found, None otherwise
    
    Raises:
        RuntimeError: If the database has not been configured
    """
    with session_scope() as session:
        # SQLAlchemy 2.x style query
        stmt = select(Goal).where(Goal.id == goal_id)
        result = session.execute(stmt)
        return result.scalar_one_or_none()


def get_all_goals() -> List[Goal]:
    """
    Retrieve all goals from the database, ordered by priority then description.
    
    Returns:
        List of Goal objects
    
    Raises:
        RuntimeError: If the database has not been configured
    """
    with session_scope() as session:
        stmt = select(Goal).order_by(Goal.priority.asc(), Goal.description.asc())
        result = session.execute(stmt)
        return list(result.scalars().all())


def update_goals(state: Dict[str, Any]) -> None:
    """
    Dynamically update existing goals based on the provided state dictionary.
    
    This function allows batch updates to goals by ID. The state dictionary
    maps goal IDs (as strings) to update dictionaries containing field 
    modifications. Only valid fields (description, priority) are updated.
    
    Args:
        state: Dictionary mapping goal ID strings to update dictionaries.
               Example: {"1": {"priority": 5}, "2": {"description": "New text"}}
    
    Raises:
        RuntimeError: If the database has not been configured
        ValueError: If state is not a dictionary
    
    Note:
        Invalid goal IDs are silently skipped (logged as warning).
        Invalid field names in updates are ignored.
    """
    if not isinstance(state, dict):
        raise ValueError("State must be a dictionary mapping goal IDs to updates")
    
    valid_fields = {'description', 'priority'}
    
    with session_scope() as session:
        for goal_id_str, updates in state.items():
            # Validate goal_id can be converted to integer
            try:
                goal_id = int(goal_id_str)
            except (ValueError, TypeError):
                logger.warning("Invalid goal ID format: %s (skipping)", goal_id_str)
                continue
            
            # Validate updates is a dictionary
            if not isinstance(updates, dict):
                logger.warning("Invalid updates for goal %s: not a dict (skipping)", goal_id_str)
                continue
            
            # Fetch goal using SQLAlchemy 2.x select style
            stmt = select(Goal).where(Goal.id == goal_id)
            result = session.execute(stmt)
            goal = result.scalar_one_or_none()
            
            if goal is None:
                logger.debug("Goal ID %d not found in database (skipping update)", goal_id)
                continue
            
            # Apply valid updates
            updated_fields = []
            for key, value in updates.items():
                if key in valid_fields:
                    if key == 'description' and isinstance(value, str):
                        value = value.strip()
                    elif key == 'priority' and not isinstance(value, int):
                        logger.warning("Invalid priority type for goal %d: %s", goal_id, type(value))
                        continue
                    
                    setattr(goal, key, value)
                    updated_fields.append(key)
                else:
                    logger.warning("Invalid field '%s' for Goal update (skipping)", key)
            
            if updated_fields:
                logger.debug("Updated goal %d: %s", goal_id, ", ".join(updated_fields))


def delete_goal(goal_id: int) -> bool:
    """
    Delete a goal by its ID.
    
    Args:
        goal_id: The integer ID of the goal to delete
    
    Returns:
        True if a goal was found and deleted, False if not found
    
    Raises:
        RuntimeError: If the database has not been configured
    """
    with session_scope() as session:
        stmt = select(Goal).where(Goal.id == goal_id)
        result = session.execute(stmt)
        goal = result.scalar_one_or_none()
        
        if goal is not None:
            session.delete(goal)
            logger.debug("Deleted goal %d", goal_id)
            return True
        return False


def clear_all_goals() -> int:
    """
    Delete all goals from the database. Useful for testing.
    
    Returns:
        Number of goals deleted
    
    Raises:
        RuntimeError: If the database has not been configured
    """
    with session_scope() as session:
        stmt = select(Goal)
        result = session.execute(stmt)
        goals = result.scalars().all()
        count = len(goals)
        
        for goal in goals:
            session.delete(goal)
        
        logger.debug("Cleared all %d goals", count)
        return count


def _selftest() -> None:
    """
    Execute comprehensive self-test using temporary SQLite database.
    
    Validates:
    - Database schema creation and Goal model mapping
    - add_goal insertion functionality
    - update_goals modification functionality
    - Error handling for invalid inputs
    - Session management and transaction safety
    
    Uses temporary directory with automatic cleanup.
    Must complete in under 20 seconds.
    
    Raises:
        AssertionError: If any test assertion fails
        Exception: If database operations fail unexpectedly
    """
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    
    try:
        # Setup temporary database
        db_path = os.path.join(temp_dir.name, 'test_goals.db')
        database_url = f"sqlite:///{db_path}"
        
        # Create engine and configure module
        test_engine = create_engine(database_url, echo=False, future=True)
        configure(engine=test_engine)
        
        # Create all tables
        IntPKModel.metadata.create_all(test_engine)
        
        logger.info("Self-test: Starting goal manager tests")
        
        # Test 1: Add goals
        add_goal("Fix broken part", 1)
        add_goal("Inspect machinery", 2)
        
        # Verify insertion using direct session (SQLAlchemy 2.x style)
        with Session(bind=test_engine) as verification_session:
            stmt = select(Goal).order_by(Goal.id)
            results = verification_session.execute(stmt)
            goals = list(results.scalars().all())
            
            assert len(goals) == 2, f"Expected 2 goals, found {len(goals)}"
            
            # Verify first goal
            goal_1 = goals[0]
            assert goal_1.description == "Fix broken part", f"Description mismatch: {goal_1.description}"
            assert goal_1.priority == 1, f"Priority mismatch: {goal_1.priority}"
            
            # Verify second goal
            goal_2 = goals[1]
            assert goal_2.description == "Inspect machinery", f"Description mismatch: {goal_2.description}"
            assert goal_2.priority == 2, f"Priority mismatch: {goal_2.priority}"
        
        # Test 2: Update goals using string keys (as per API spec)
        update_goals({
            "1": {"priority": 3}, 
            "2": {"description": "Check safety protocols"}
        })
        
        # Verify updates
        with Session(bind=test_engine) as verification_session:
            # Check goal 1 priority update
            stmt1 = select(Goal).where(Goal.id == 1)
            g1 = verification_session.execute(stmt1).scalar_one_or_none()
            assert g1 is not None, "Goal 1 not found after update"
            assert g1.priority == 3, f"Expected priority 3, got {g1.priority}"
            assert g1.description == "Fix broken part", "Description should remain unchanged"
            
            # Check goal 2 description update
            stmt2 = select(Goal).where(Goal.id == 2)
            g2 = verification_session.execute(stmt2).scalar_one_or_none()
            assert g2 is not None, "Goal 2 not found after update"
            assert g2.description == "Check safety protocols", f"Expected new description, got {g2.description}"
            assert g2.priority == 2, "Priority should remain unchanged"
        
        # Test 3: Error handling - empty goal description
        try:
            add_goal("", 1)
            assert False, "Should have raised ValueError for empty goal"
        except ValueError as e:
            assert "non-empty" in str(e).lower() or "empty" in str(e).lower()
        
        # Test 4: Error handling - invalid priority type
        try:
            add_goal("Valid goal", "high")  # type: ignore
            assert False, "Should have raised ValueError for invalid priority type"
        except ValueError:
            pass
        
        # Test 5: Update non-existent goal (should not raise, should log warning)
        update_goals({"999": {"priority": 5}})
        
        # Verify count unchanged
        with Session(bind=test_engine) as verification_session:
            count_stmt = select(func.count()).select_from(Goal)
            count = verification_session.execute(count_stmt).scalar()
            assert count == 2, f"Count should still be 2, got {count}"
        
        # Test 6: Invalid field in update (should be ignored)
        update_goals({"1": {"invalid_field": "value", "priority": 10}})
        
        with Session(bind=test_engine) as verification_session:
            stmt = select(Goal).where(Goal.id == 1)
            g = verification_session.execute(stmt).scalar_one()
            assert g.priority == 10, "Valid field should be updated"
            assert not hasattr(g, 'invalid_field') or getattr(g, 'invalid_field', None) is None
        
        logger.info("Self-test: All assertions passed successfully")
        
    finally:
        # Cleanup
        reset_configuration()
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
