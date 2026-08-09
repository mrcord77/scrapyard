"""
reflection_engine — Enables agents to analyze past actions and refine their planning strategies through structured reflection. Supports continuous learning and adaptation by capturing feedback and updating future plans a

### PART-META-JSON
{
  "name": "reflection_engine",
  "layer": "agents",
  "purpose": "Enables agents to analyze past actions and refine their planning strategies through structured reflection. Supports continuous learning and adaptation by capturing feedback and updating future plans a",
  "addition": true,
  "status": "core",
  "dependencies": [
    "planner"
  ],
  "inputs": "Public API: set_session_context(session); reflect_on_action(action); update_plan(plan); Reflection(...); Action(...); Plan(...).",
  "outputs": "Returns: set_session_context -> None; reflect_on_action -> None; update_plan -> None.",
  "files_created": [
    "reflections"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.reflection_engine`.",
  "example": "from scrapyard.agents.reflection_engine import *",
  "import_path": "scrapyard.agents.reflection_engine"
}
### END-PART-META
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable, get_type_hints

from sqlalchemy import Integer, Text, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel

# Module-level logger
logger = logging.getLogger(__name__)

# Thread-local storage for session context to avoid passing session through API
_thread_local = threading.local()


def _get_session() -> Session:
    """Retrieve the current session from thread-local context."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        raise RuntimeError("No active session context. Use set_session_context() or context manager.")
    return session


def set_session_context(session: Optional[Session]) -> None:
    """Set the current database session in the thread-local context."""
    _thread_local.session = session


# SQLAlchemy ORM Model
class Reflection(IntPKModel):
    """Stores reflection records for agent actions."""
    __tablename__ = "reflections"
    
    action_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    feedback: Mapped[str] = mapped_column(Text, nullable=False)


# Protocol definitions for type safety
@runtime_checkable
class Action(Protocol):
    """Protocol for action objects that can be reflected upon."""
    id: int
    outcome: Optional[str] = None
    error: Optional[str] = None
    
    def get_feedback(self) -> str:
        """Generate or return feedback string for this action."""
        ...


@runtime_checkable
class Plan(Protocol):
    """Protocol for plan objects."""
    id: int
    strategy: Optional[str] = None


def reflect_on_action(action: Action) -> None:
    """
    Analyzes an action and creates a reflection record in the current session.
    
    Does NOT commit the session - the caller is responsible for commit.
    """
    session = _get_session()
    
    # Generate feedback from action if method exists, otherwise construct from attributes
    if hasattr(action, "get_feedback") and callable(action.get_feedback):
        feedback = action.get_feedback()
    else:
        parts = []
        if hasattr(action, "outcome") and action.outcome:
            parts.append(f"outcome={action.outcome}")
        if hasattr(action, "error") and action.error:
            parts.append(f"error={action.error}")
        feedback = "; ".join(parts) if parts else "reflection_recorded"
    
    reflection = Reflection(
        action_id=action.id,
        feedback=feedback
    )
    
    session.add(reflection)
    logger.debug(f"Reflection created for action {action.id}: {feedback[:50]}...")
    # Intentionally no commit here - requirement: no side effects during reflection


def update_plan(plan: Plan) -> None:
    """
    Updates a plan by integrating with the planner dependency.
    
    Lazily imports the planner module to avoid import-time dependencies.
    Falls back to local registry if planner is unavailable.
    """
    # Lazy import of planner to satisfy dependency requirement and avoid import errors
    try:
        from scrapyard.agents import planner
        if hasattr(planner, "update_plan"):
            planner.update_plan(plan)
            logger.debug(f"Plan {plan.id} updated via planner module")
            return
        else:
            logger.warning("Planner module missing update_plan function")
    except ImportError:
        logger.debug("Planner module not available for update_plan")
    
    # Fallback: store in module-level registry for retrieval/testing
    if not hasattr(update_plan, "_plan_registry"):
        update_plan._plan_registry = {}  # type: ignore[attr-defined]
    
    import time as _time
    update_plan._plan_registry[plan.id] = {  # type: ignore[attr-defined]
        "id": plan.id,
        "strategy": getattr(plan, "strategy", None),
        "timestamp": _time.time(),  # real update time of this registry entry
    }
    logger.debug(f"Plan {plan.id} stored in local registry")


def _selftest() -> None:
    """
    Self-contained selftest using temporary SQLite database.
    Verifies all spec requirements without external dependencies.
    """
    import tempfile
    import os
    import time
    
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "reflection_test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        
        # Setup session
        SessionFactory = sessionmaker(bind=engine)
        session = SessionFactory()
        
        try:
            set_session_context(session)
            
            # Define test Action implementation
            @dataclass
            class MockAction:
                id: int
                outcome: Optional[str] = None
                error: Optional[str] = None
                
                def get_feedback(self) -> str:
                    parts = []
                    if self.outcome:
                        parts.append(f"Outcome: {self.outcome}")
                    if self.error:
                        parts.append(f"Error: {self.error}")
                    return " | ".join(parts) if parts else "No details"
            
            # Test: Reflection records are created for actions
            action = MockAction(id=42, outcome="completed", error=None)
            reflect_on_action(action)
            
            # Verify: No database commits during reflection (check session state)
            assert session.new, "Expected pending objects in session (no commit yet)"
            assert len(session.new) == 1, "Expected exactly one new reflection"
            pending_reflection = list(session.new)[0]
            assert isinstance(pending_reflection, Reflection), "Pending object should be Reflection"
            assert pending_reflection.action_id == 42
            assert "completed" in pending_reflection.feedback
            
            # Commit and verify retrievable
            session.commit()
            
            # Verify in database
            result = session.execute(select(Reflection).where(Reflection.action_id == 42))
            db_record = result.scalar_one_or_none()
            assert db_record is not None, "Reflection should be persisted after explicit commit"
            assert db_record.feedback == "Outcome: completed"
            
            # Test: Plan updates are stored and retrievable
            @dataclass
            class MockPlan:
                id: int
                strategy: str = "default"
            
            plan = MockPlan(id=1, strategy="aggressive_optimization")
            update_plan(plan)
            
            # Verify plan was stored (in fallback registry since planner won't exist)
            assert hasattr(update_plan, "_plan_registry"), "Plan registry should be populated"
            stored = update_plan._plan_registry.get(1)  # type: ignore[attr-defined]
            assert stored is not None, "Plan should be stored"
            assert stored["strategy"] == "aggressive_optimization"
            
            # Test: Type hints are enforced (check annotations exist)
            hints_action = get_type_hints(reflect_on_action)
            assert "action" in hints_action, "reflect_on_action missing type hint for action"
            
            hints_plan = get_type_hints(update_plan)
            assert "plan" in hints_plan, "update_plan missing type hint for plan"
            
            # Verify no unhandled exceptions occurred (we got here)
            
        finally:
            set_session_context(None)
            session.close()
            engine.dispose()
    
    elapsed = time.time() - start_time
    assert elapsed < 20, f"Selftest exceeded 20 seconds: {elapsed:.2f}s"
    logger.info(f"_selftest completed successfully in {elapsed:.3f}s")


if __name__ == "__main__":
    _selftest()
