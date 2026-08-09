"""
escalation_rule - Evaluate escalation rules against pending requests and emit escalation actions.

### PART-META-JSON
{
  "name": "escalation_rule",
  "layer": "approvals_workfl",
  "purpose": "Evaluate escalation rules against pending requests and emit escalation actions.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "evaluate_condition(condition, request); apply_escalation_rules(request, session).",
  "outputs": "EscalationRule / EscalationAction rows; actions produced for matched rules.",
  "files_created": [],
  "security_notes": "Rule conditions are structured dicts (field/operator/value) interpreted by a fixed evaluator - no eval of stored strings, unknown operators are rejected. Escalations change who can approve spend: restrict rule-table writes to admins.",
  "ai_usage": "Import what you need from `scrapyard.approvals_workfl.escalation_rule`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.approvals_workfl.escalation_rule import evaluate_condition",
  "import_path": "scrapyard.approvals_workfl.escalation_rule"
}
### END-PART-META
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    String, Integer, Boolean, DateTime, JSON, ForeignKey, Index, select, create_engine
)
from sqlalchemy.orm import Mapped, mapped_column, Session, validates, sessionmaker
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


@dataclass
class Request:
    """Represents an approval request for escalation checking."""
    id: int
    created_at: datetime
    status: str = "pending"
    current_approver: Optional[str] = None
    request_type: str = "default"
    metadata: Dict[str, Any] = field(default_factory=dict)


class EscalationAction(IntPKModel):
    """Database model for escalation actions."""
    __tablename__ = "escalation_actions"
    
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=dict)
    target: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    def __repr__(self) -> str:
        return f"<EscalationAction(id={self.id}, type={self.action_type}, target={self.target})>"


class EscalationRule(IntPKModel):
    """Database model for escalation rules with conditions and priorities."""
    __tablename__ = "escalation_rules"
    
    condition: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    action_id: Mapped[int] = mapped_column(ForeignKey("escalation_actions.id"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    
    __table_args__ = (
        Index('idx_escalation_priority_active', 'priority', 'is_active'),
        Index('idx_escalation_action_id', 'action_id'),
    )
    
    @validates('condition')
    def validate_condition(self, key: str, condition: Any) -> Dict[str, Any]:
        if not isinstance(condition, dict):
            raise ValueError(f"Condition must be a dictionary, got {type(condition)}")
        if 'type' not in condition:
            raise ValueError("Condition must have a 'type' key")
        return condition
    
    @validates('priority')
    def validate_priority(self, key: str, priority: Any) -> int:
        if not isinstance(priority, int):
            raise ValueError(f"Priority must be an integer, got {type(priority)}")
        return priority
    
    @validates('action_id')
    def validate_action_id(self, key: str, action_id: Any) -> int:
        if not isinstance(action_id, int):
            raise ValueError(f"Action ID must be an integer, got {type(action_id)}")
        return action_id
    
    def __repr__(self) -> str:
        return f"<EscalationRule(id={self.id}, priority={self.priority}, active={self.is_active}, version={self.version})>"


def evaluate_condition(condition: Dict[str, Any], request: Request) -> bool:
    """
    Evaluate a condition dictionary against a request.
    
    Supported condition types:
    - time_based: {'type': 'time_based', 'hours': int}
    - approver_based: {'type': 'approver_based', 'approver': str|None}
    - status_based: {'type': 'status_based', 'status': str}
    - composite: {'type': 'composite', 'operator': 'AND'|'OR', 'conditions': [...]}
    """
    cond_type = condition.get("type")
    
    if cond_type == "time_based":
        hours = condition.get("hours", 24)
        if not isinstance(hours, (int, float)):
            raise ValueError(f"Hours must be numeric, got {type(hours)}")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return request.created_at < cutoff
    
    elif cond_type == "approver_based":
        target_approver = condition.get("approver")
        if target_approver is None:
            return request.current_approver is None
        return request.current_approver == target_approver
    
    elif cond_type == "status_based":
        return request.status == condition.get("status")
    
    elif cond_type == "composite":
        operator = condition.get("operator", "AND")
        sub_conditions = condition.get("conditions", [])
        if not isinstance(sub_conditions, list):
            raise ValueError("Composite conditions must be a list")
        
        results = [evaluate_condition(c, request) for c in sub_conditions]
        
        if operator == "AND":
            return all(results)
        elif operator == "OR":
            return any(results)
        else:
            raise ValueError(f"Unknown operator: {operator}")
    
    else:
        raise ValueError(f"Unknown condition type: {cond_type}")


def apply_escalation_rules(request: Request, session: Session) -> List[EscalationAction]:
    """
    Apply escalation rules to a request.
    
    Evaluates all active rules in priority order (lower number = higher priority)
    and returns actions for all matching rules.
    
    Args:
        request: The request to evaluate
        session: Database session for querying rules
        
    Returns:
        List of EscalationAction objects for matching rules, ordered by priority
    """
    stmt = (
        select(EscalationRule)
        .where(EscalationRule.is_active == True)
        .order_by(EscalationRule.priority.asc())
    )
    
    rules = session.execute(stmt).scalars().all()
    matching_actions: List[EscalationAction] = []
    
    for rule in rules:
        try:
            if evaluate_condition(rule.condition, request):
                action_stmt = select(EscalationAction).where(EscalationAction.id == rule.action_id)
                action = session.execute(action_stmt).scalar_one_or_none()
                if action:
                    matching_actions.append(action)
        except Exception as e:
            logger.error(f"Error evaluating rule {rule.id}: {e}")
            continue
    
    return matching_actions


def _selftest():
    """Module self-test using temporary SQLite database."""
    import tempfile
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_escalation.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
        
        # Create all tables
        IntPKModel.metadata.create_all(engine)
        
        SessionFactory = sessionmaker(bind=engine)
        session = SessionFactory()
        
        try:
            # Test 1: Database model creation and persistence
            action_email = EscalationAction(
                action_type="email",
                details={"template": "escalation_notice", "subject": "Approval Required"},
                target="manager@example.com"
            )
            action_reassign = EscalationAction(
                action_type="reassign",
                details={"to_role": "senior_manager"},
                target="senior_manager"
            )
            action_sla = EscalationAction(
                action_type="sla_trigger",
                details={"severity": "high"},
                target="sla_system"
            )
            
            session.add_all([action_email, action_reassign, action_sla])
            session.commit()
            
            assert action_email.id is not None, "Action should have ID after commit"
            assert action_reassign.id is not None, "Action should have ID after commit"
            
            # Test 2: Rule creation with validation
            rule_time = EscalationRule(
                condition={"type": "time_based", "hours": 24},
                action_id=action_email.id,
                priority=1,
                is_active=True,
                version=1
            )
            rule_approver = EscalationRule(
                condition={"type": "approver_based", "approver": None},
                action_id=action_reassign.id,
                priority=2,
                is_active=True,
                version=1
            )
            rule_status = EscalationRule(
                condition={"type": "status_based", "status": "pending"},
                action_id=action_sla.id,
                priority=3,
                is_active=True,
                version=2
            )
            # Inactive rule (should not match)
            rule_inactive = EscalationRule(
                condition={"type": "time_based", "hours": 1},
                action_id=action_email.id,
                priority=0,  # High priority but inactive
                is_active=False,
                version=1
            )
            
            session.add_all([rule_time, rule_approver, rule_status, rule_inactive])
            session.commit()
            
            # Verify persistence
            all_rules = session.execute(select(EscalationRule)).scalars().all()
            assert len(all_rules) == 4, f"Expected 4 rules, got {len(all_rules)}"
            
            # Test 3: Type validation prevents invalid data
            try:
                bad_rule = EscalationRule(
                    condition="invalid_string",  # Should be dict
                    action_id=action_email.id,
                    priority=1,
                    is_active=True
                )
                session.add(bad_rule)
                session.commit()
                assert False, "Should have raised ValueError for invalid condition type"
            except ValueError:
                session.rollback()
            
            try:
                bad_rule2 = EscalationRule(
                    condition={"type": "time_based", "hours": 24},
                    action_id=action_email.id,
                    priority="high",  # Should be int
                    is_active=True
                )
                session.add(bad_rule2)
                session.commit()
                assert False, "Should have raised ValueError for invalid priority type"
            except ValueError:
                session.rollback()
            
            # Test 4: Rule conditions evaluated correctly
            now = datetime.now(timezone.utc)
            
            # Request 1: Old request, no approver (matches time and approver rules)
            old_request = Request(
                id=1,
                created_at=now - timedelta(hours=25),
                status="pending",
                current_approver=None
            )
            
            # Request 2: New request, no approver (matches only approver rule)
            new_request = Request(
                id=2,
                created_at=now - timedelta(hours=1),
                status="pending",
                current_approver=None
            )
            
            # Request 3: Old request with approver (matches only time rule)
            assigned_request = Request(
                id=3,
                created_at=now - timedelta(hours=48),
                status="pending",
                current_approver="someone"
            )
            
            # Test 5: Actions applied when conditions match
            results_old = apply_escalation_rules(old_request, session)
            assert len(results_old) == 3, f"Expected 3 actions for old request, got {len(results_old)}"
            # Check priority ordering (1, 2, 3)
            assert results_old[0].action_type == "email"
            assert results_old[1].action_type == "reassign"
            assert results_old[2].action_type == "sla_trigger"
            
            results_new = apply_escalation_rules(new_request, session)
            # Should match approver rule (no approver) and status rule (pending), but not time (only 1 hour old)
            # Actually, approver rule matches (None), status rule matches (pending)
            # Wait, rule_approver checks for approver None, rule_status checks for status pending
            assert len(results_new) == 2, f"Expected 2 actions for new request, got {len(results_new)}"
            types = [r.action_type for r in results_new]
            assert "reassign" in types
            assert "sla_trigger" in types
            
            results_assigned = apply_escalation_rules(assigned_request, session)
            # Should match time rule (48 hours > 24) and status rule (pending), but not approver (has someone)
            assert len(results_assigned) == 2, f"Expected 2 actions for assigned request, got {len(results_assigned)}"
            types = [r.action_type for r in results_assigned]
            assert "email" in types
            assert "sla_trigger" in types
            
            # Test 6: Rule deactivation prevents rule application
            # The inactive rule has priority 0 and 1 hour condition
            # If it were active, it would match old_request (25 hours > 1)
            # But it's inactive, so we should not see an extra email action
            # We already checked old_request has exactly 3 actions, not 4
            
            # Test 7: Composite conditions
            composite_action = EscalationAction(
                action_type="composite_action",
                details={},
                target="system"
            )
            session.add(composite_action)
            session.commit()
            
            composite_rule = EscalationRule(
                condition={
                    "type": "composite",
                    "operator": "AND",
                    "conditions": [
                        {"type": "status_based", "status": "pending"},
                        {"type": "time_based", "hours": 12}
                    ]
                },
                action_id=composite_action.id,
                priority=0,  # Highest priority
                is_active=True
            )
            session.add(composite_rule)
            session.commit()
            
            # Refresh results for old request with new rule
            results_old_composite = apply_escalation_rules(old_request, session)
            # Now should have 4 actions: composite (priority 0), email (1), reassign (2), sla (3)
            assert len(results_old_composite) == 4
            assert results_old_composite[0].action_type == "composite_action"
            
            # Test 8: Versioning support
            assert rule_time.version == 1
            rule_time.version = 2
            session.commit()
            session.refresh(rule_time)
            assert rule_time.version == 2
            
            # Test 9: Updated_at changes on update
            old_updated = rule_status.updated_at
            rule_status.priority = 10
            session.commit()
            session.refresh(rule_status)
            assert rule_status.updated_at > old_updated
            
            print("All selftest assertions passed!")
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
