"""
self_critique_engine — Performs self-critique of agent actions to identify mistakes and improve future behavior. Integrates with reflection systems to enable adaptive, learning-based agents.

### PART-META-JSON
{
  "name": "self_critique_engine",
  "layer": "agents",
  "purpose": "Performs self-critique of agent actions to identify mistakes and improve future behavior. Integrates with reflection systems to enable adaptive, learning-based agents.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "reflection_engine"
  ],
  "inputs": "Public API: critique_action(action); suggest_improvements(plan); Critique(...).",
  "outputs": "Returns: critique_action -> List[Dict[str, Any]]; suggest_improvements -> List[Dict[str, Any]].",
  "files_created": [
    "critiques"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.self_critique_engine`.",
  "example": "from scrapyard.agents.self_critique_engine import *",
  "import_path": "scrapyard.agents.self_critique_engine"
}
### END-PART-META
"""

import json
import logging
import os
import tempfile
from typing import Any, List, Dict

from sqlalchemy import ForeignKey, Text, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class Critique(IntPKModel):
    __tablename__ = "critiques"
    action_id: Mapped[int] = mapped_column(ForeignKey("self_critique_engine_actions.id"))
    issues: Mapped[str] = mapped_column(Text, nullable=False)


def critique_action(action: Any) -> List[Dict[str, Any]]:
    """Analyze an action and return a list of identified issues."""
    issues: List[Dict[str, Any]] = []
    
    if action is None:
        return [{"severity": "error", "type": "input", "description": "Action is None"}]
    
    if isinstance(action, dict):
        if not action.get("description"):
            issues.append({
                "severity": "medium",
                "type": "clarity",
                "description": "Action lacks description"
            })
        if action.get("risk_level") == "high" and not action.get("mitigation"):
            issues.append({
                "severity": "high",
                "type": "safety",
                "description": "High risk action without mitigation strategy"
            })
        if not action.get("expected_outcome"):
            issues.append({
                "severity": "low",
                "type": "planning",
                "description": "No expected outcome defined"
            })
    elif isinstance(action, str):
        if len(action.strip()) < 10:
            issues.append({
                "severity": "medium",
                "type": "clarity",
                "description": "Action description is too vague"
            })
    else:
        issues.append({
            "severity": "info",
            "type": "structure",
            "description": "Action is not in standard dict format"
        })
    
    return issues


def suggest_improvements(plan: Any) -> List[Dict[str, Any]]:
    """Analyze a plan and suggest actionable improvements."""
    suggestions: List[Dict[str, Any]] = []
    
    if plan is None:
        return [{"priority": "high", "category": "input", "suggestion": "Plan is undefined"}]
    
    if isinstance(plan, dict):
        steps = plan.get("steps", [])
        if not steps:
            suggestions.append({
                "priority": "high",
                "category": "completeness",
                "suggestion": "Plan has no defined steps"
            })
        elif len(steps) > 10:
            suggestions.append({
                "priority": "medium",
                "category": "complexity",
                "suggestion": "Consider breaking plan into smaller sub-plans"
            })
        
        if not plan.get("fallback"):
            suggestions.append({
                "priority": "medium",
                "category": "robustness",
                "suggestion": "Add fallback strategy for plan failure"
            })
            
        if not plan.get("review_points"):
            suggestions.append({
                "priority": "low",
                "category": "monitoring",
                "suggestion": "Add review points for long-running plans"
            })
    elif isinstance(plan, list):
        if len(plan) < 2:
            suggestions.append({
                "priority": "low",
                "category": "structure",
                "suggestion": "Plan seems overly simplistic"
            })
    else:
        suggestions.append({
            "priority": "medium",
            "category": "type",
            "suggestion": "Plan should be structured data (dict or list)"
        })
    
    return suggestions


def _selftest() -> bool:
    """Offline self-test for the self_critique_engine module."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_critique.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        # Define Action model for FK testing using same base as Critique
        class Action(IntPKModel):
            __tablename__ = "self_critique_engine_actions"
            name: Mapped[str] = mapped_column(Text)
        
        # Create all tables
        IntPKModel.metadata.create_all(engine)
        
        # Test 1: Critique action with synthetic input returns structured issues
        test_action = {
            "risk_level": "high",
            # Missing mitigation and description to trigger issues
        }
        issues = critique_action(test_action)
        assert isinstance(issues, list), "critique_action must return a list"
        assert len(issues) > 0, "Should detect issues in high-risk action without mitigation"
        assert any(i.get("type") == "safety" for i in issues), "Should detect safety issue"
        
        # Test 2: Suggest improvements on a sample plan
        test_plan = {
            "steps": list(range(15)),  # Too many steps
            # Missing fallback
        }
        improvements = suggest_improvements(test_plan)
        assert isinstance(improvements, list), "suggest_improvements must return a list"
        assert any("sub-plans" in str(i.get("suggestion", "")) for i in improvements), "Should suggest breaking into sub-plans"
        
        # Test 3: Store critique in database and retrieve it
        with Session(engine) as session:
            # Create action first for FK
            action = Action(name="test_action")
            session.add(action)
            session.commit()
            
            # Store critique
            critique = Critique(
                action_id=action.id,
                issues=json.dumps(issues)
            )
            session.add(critique)
            session.commit()
            
            # Retrieve and verify
            retrieved = session.execute(
                select(Critique).where(Critique.action_id == action.id)
            ).scalar_one_or_none()
            
            assert retrieved is not None, "Should retrieve stored critique"
            assert retrieved.issues == json.dumps(issues), "Stored issues should match original"
            
            # Verify deserialized content
            stored_data = json.loads(retrieved.issues)
            assert isinstance(stored_data, list)
            assert len(stored_data) == len(issues)
        
        # Test 4: Handle invalid inputs gracefully
        null_issues = critique_action(None)
        assert isinstance(null_issues, list), "Should handle None action gracefully"
        assert len(null_issues) > 0, "Should report error for None input"
        
        null_suggestions = suggest_improvements(None)
        assert isinstance(null_suggestions, list), "Should handle None plan gracefully"
        
        # Cleanup
        engine.dispose()
    
    return True


if __name__ == "__main__":
    _selftest()
