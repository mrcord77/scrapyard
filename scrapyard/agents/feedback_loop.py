"""
feedback_loop — Enables continuous learning by capturing and applying feedback from agent actions. It supports iterative refinement of plans through data-driven insights.

### PART-META-JSON
{
  "name": "feedback_loop",
  "layer": "agents",
  "purpose": "Enables continuous learning by capturing and applying feedback from agent actions. It supports iterative refinement of plans through data-driven insights.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure_engine(engine); collect_feedback(action); apply_feedback(plan, feedback); Action(...); Feedback(...); Plan(...) (plus more).",
  "outputs": "Returns: configure_engine -> None; collect_feedback -> Feedback; apply_feedback -> Plan.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.feedback_loop`.",
  "example": "from scrapyard.agents.feedback_loop import *",
  "import_path": "scrapyard.agents.feedback_loop"
}
### END-PART-META
"""

from sqlalchemy import JSON, Integer, Index, UniqueConstraint, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from dataclasses import dataclass
from typing import Dict, Any
import os
import json
import logging
import tempfile

logger = logging.getLogger(__name__)

# Module-level engine storage for database connectivity
_engine = None

@dataclass
class Action:
    id: int
    details: str

@dataclass
class Feedback:
    id: int
    action_id: int
    details: Dict[str, Any]

@dataclass
class Plan:
    id: int
    details: str

class FeedbackModel(IntPKModel):
    __tablename__ = 'feedback'

    action_id: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        Index('idx_feedback_action_id', 'action_id'),
        UniqueConstraint('action_id', name='uq_feedback_action_id')
    )

def configure_engine(engine) -> None:
    """Configure the database engine for the module."""
    global _engine
    _engine = engine

def _get_engine():
    """Get the configured engine or raise an error."""
    if _engine is None:
        raise RuntimeError("Database engine not configured. Call configure_engine() first.")
    return _engine

def collect_feedback(action: Action) -> Feedback:
    """
    Captures feedback from an executed action and stores it in the database.
    
    Args:
        action: The action to collect feedback from
        
    Returns:
        Feedback: The stored feedback record with assigned ID
    """
    engine = _get_engine()
    with Session(engine) as session:
        feedback_model = FeedbackModel(
            action_id=action.id,
            details=json.loads(action.details)
        )
        session.add(feedback_model)
        session.commit()
        # Extract data while session is still active
        feedback = Feedback(
            id=feedback_model.id,
            action_id=feedback_model.action_id,
            details=feedback_model.details
        )
        logger.info(f"Collected feedback {feedback.id} for action {action.id}")
        return feedback

def apply_feedback(plan: Plan, feedback: Feedback) -> Plan:
    """
    Applies feedback to refine a plan by merging feedback details into plan details.
    
    Args:
        plan: The original plan to refine
        feedback: The feedback to apply
        
    Returns:
        Plan: A new plan with feedback incorporated
    """
    plan_details: Dict[str, Any] = json.loads(plan.details)
    
    # Merge feedback details - only add keys not already present
    for key, value in feedback.details.items():
        if key not in plan_details:
            plan_details[key] = value
    
    updated_plan = Plan(
        id=plan.id,
        details=json.dumps(plan_details)
    )
    
    logger.info(f"Applied feedback {feedback.id} to plan {plan.id}")
    return updated_plan

def _selftest():
    """
    Self-contained test suite for the feedback_loop module.
    Uses temporary SQLite database to verify functionality.
    """
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting feedback_loop self-test")
    
    # Save original engine to restore later (prevent state leak)
    original_engine = _engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_file = os.path.join(tmpdir, 'feedback.db')
        engine = create_engine(f"sqlite:///{db_file}", echo=False)
        
        try:
            configure_engine(engine)
            IntPKModel.metadata.create_all(engine)
            
            # Test collect_feedback stores action details in the feedback table
            action_data = {'action': 'collect_data', 'status': 'success'}
            action1 = Action(id=1, details=json.dumps(action_data))
            feedback1 = collect_feedback(action1)
            
            assert isinstance(feedback1, Feedback), "Feedback should be an instance of Feedback"
            assert feedback1.id > 0, "Feedback ID should be positive"
            assert feedback1.action_id == 1, "Feedback action_id should match"
            
            # Verify storage using select()
            with Session(engine) as session:
                stmt = select(FeedbackModel).where(FeedbackModel.id == feedback1.id)
                result = session.execute(stmt).scalar_one_or_none()
                assert result is not None, "Feedback should be stored in database"
                assert result.details == action_data, "Stored details should match action details"
            
            # Test apply_feedback modifies a plan based on feedback data
            plan1 = Plan(id=1, details=json.dumps({'plan': 'collect_data', 'status': 'success'}))
            updated_plan1 = apply_feedback(plan1, feedback1)
            
            assert isinstance(updated_plan1, Plan), "Updated plan should be an instance of Plan"
            updated_details = json.loads(updated_plan1.details)
            assert updated_details['action'] == 'collect_data', "Plan details should be updated with feedback action"
            
            logger.info("Self-test passed successfully")
            
        finally:
            engine.dispose()
            configure_engine(original_engine)

if __name__ == "__main__":
    _selftest()
