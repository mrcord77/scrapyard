"""
executor — Executes agent plans by decomposing them into steps and performing actions. It acts as the execution engine for the agents_core domain, ensuring plans are carried out systematically and reliably.

### PART-META-JSON
{
  "name": "executor",
  "layer": "agents",
  "purpose": "Executes agent plans by decomposing them into steps and performing actions. It acts as the execution engine for the agents_core domain, ensuring plans are carried out systematically and reliably.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: register_handler(name, fn); unregister_handler(name); add_action(db, name, status); get_action(db, action_id); delete_action(db, action_id); Action(...); ActionStatus(...) (plus more).",
  "outputs": "Returns: register_handler -> None; unregister_handler -> None; add_action -> Action; get_action -> Optional[Action]; delete_action -> bool.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.executor`.",
  "example": "from scrapyard.agents.executor import *",
  "import_path": "scrapyard.agents.executor"
}
### END-PART-META
"""

import logging
import os
import tempfile
from typing import Callable, Dict, List, Optional, Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

# Planner integration with fallback for offline testing
try:
    from scrapyard.agents.planner import Plan, decompose_plan
except ImportError:
    # Fallback definitions for self-contained testing
    class Plan:
        def __init__(self, name: str, steps: List[str]):
            self.name = name
            self.steps = steps
    
    def decompose_plan(plan: Plan) -> List[Any]:
        """Fallback decomposition that returns simple objects with name attribute."""
        return [type('Step', (), {'name': s}) for s in plan.steps]

logger = logging.getLogger(__name__)


class Action(IntPKModel):
    """ORM model for tracking actions in the database."""
    __tablename__ = "executor_actions"
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")


class ActionStatus(BaseModel):
    """Pydantic model representing the status of an action."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    result: Optional[str] = None


# Registry of real action handlers: action name -> callable(action_name) -> Any.
# step() executes the matching handler (if any) and records its result; actions
# without a registered handler are treated as declarative no-op steps.
_ACTION_HANDLERS: Dict[str, Callable[[str], Any]] = {}


def register_handler(name: str, fn: Callable[[str], Any]) -> None:
    """Register the callable that actually performs an action."""
    if not callable(fn):
        raise TypeError("handler must be callable")
    _ACTION_HANDLERS[name] = fn


def unregister_handler(name: str) -> None:
    _ACTION_HANDLERS.pop(name, None)


def add_action(db: Session, name: str, status: str = "pending") -> Action:
    """Add a new action to the database."""
    action = Action(name=name, status=status)
    db.add(action)
    db.flush()
    db.refresh(action)
    logger.debug(f"Added action id={action.id}, name={name}")
    return action


def get_action(db: Session, action_id: int) -> Optional[Action]:
    """Retrieve an action by its ID."""
    return db.get(Action, action_id)


def delete_action(db: Session, action_id: int) -> bool:
    """Delete an action by its ID."""
    action = get_action(db, action_id)
    if action is None:
        logger.debug(f"Action {action_id} not found for deletion")
        return False
    db.delete(action)
    db.flush()
    logger.debug(f"Deleted action {action_id}")
    return True


def step(db: Session, action: Action) -> ActionStatus:
    """Execute a single action step and update its status.

    If a handler was registered for the action name it is actually invoked and
    its return value recorded; otherwise the step completes as a declarative
    no-op (a plan step with no side effects)."""
    try:
        logger.info(f"Executing step: {action.name} (id={action.id})")
        handler = _ACTION_HANDLERS.get(action.name)
        result_repr: Optional[str] = None
        if handler is not None:
            result = handler(action.name)
            result_repr = repr(result)
        action.status = "completed"
        db.flush()
        logger.info(f"Step completed: {action.name}")
        status = ActionStatus.model_validate(action)
        status.result = result_repr
        return status
    except Exception as e:
        action.status = "failed"
        db.flush()
        logger.error(f"Step failed: {action.name}, error: {e}")
        raise


def execute_steps(db: Session, plan: Plan) -> List[ActionStatus]:
    """Execute a plan by decomposing it into steps and processing each."""
    logger.info(f"Starting execution of plan: {getattr(plan, 'name', 'unnamed')}")
    
    # Decompose plan using planner module
    plan_steps = decompose_plan(plan)
    results: List[ActionStatus] = []
    
    for step_def in plan_steps:
        # Create action record
        action = add_action(db, step_def.name)
        # Execute step
        status = step(db, action)
        results.append(status)
    
    logger.info(f"Completed execution of plan with {len(results)} steps")
    return results


def _selftest() -> None:
    """Self-contained offline test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        # Create tables
        Action.metadata.create_all(engine)
        
        with Session(engine) as session:
            # Test add_action
            action1 = add_action(session, "test_step_1")
            assert action1.id is not None
            assert action1.name == "test_step_1"
            assert action1.status == "pending"
            
            # Test get_action
            retrieved = get_action(session, action1.id)
            assert retrieved is not None
            assert retrieved.name == "test_step_1"
            
            # Test step execution with a REAL registered handler
            executed = []
            register_handler("test_step_1", lambda name: executed.append(name) or f"did:{name}")
            status = step(session, action1)
            assert isinstance(status, ActionStatus)
            assert status.status == "completed"
            assert status.id == action1.id
            assert executed == ["test_step_1"], "handler must actually run"
            assert status.result == repr("did:test_step_1")
            unregister_handler("test_step_1")

            # Failing handler marks the action failed and re-raises
            fail_action = add_action(session, "explode")
            register_handler("explode", lambda name: 1 / 0)
            try:
                step(session, fail_action)
                raise AssertionError("expected handler failure to propagate")
            except ZeroDivisionError:
                pass
            assert fail_action.status == "failed"
            unregister_handler("explode")
            delete_action(session, fail_action.id)
            
            # Verify status updated in DB via flush (no commit yet, but visible in session)
            db_action = session.get(Action, action1.id)
            assert db_action is not None
            assert db_action.status == "completed"
            
            # Test execute_steps with plan decomposition
            test_plan = Plan(name="integration_plan", steps=["step_a", "step_b", "step_c"])
            statuses = execute_steps(session, test_plan)
            
            assert len(statuses) == 3
            assert all(isinstance(s, ActionStatus) for s in statuses)
            assert all(s.status == "completed" for s in statuses)
            assert [s.name for s in statuses] == ["step_a", "step_b", "step_c"]
            
            # Verify all actions in database
            all_actions = session.execute(select(Action)).scalars().all()
            # 1 initial + 3 from plan = 4 total
            assert len(all_actions) == 4
            
            # Test delete_action
            deleted = delete_action(session, action1.id)
            assert deleted is True
            assert get_action(session, action1.id) is None
            
            # Verify deletion flushed
            remaining = session.execute(select(Action)).scalars().all()
            assert len(remaining) == 3
            
            # Test delete non-existent
            not_deleted = delete_action(session, 99999)
            assert not_deleted is False
            
        logger.info("_selftest passed successfully")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
