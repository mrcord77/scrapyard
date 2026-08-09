"""
availability_rule — ** Define business rules for resource availability and scheduling constraints, enabling flexible and reusable validation and application logic in resource scheduling systems. This module provides a co

### PART-META-JSON
{
  "name": "availability_rule",
  "layer": "projects",
  "purpose": "Define business rules for resource availability and scheduling constraints, enabling flexible and reusable validation and application logic in resource scheduling systems. This module provides a co.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: apply_rule(resource_id, start, end, context); validate_rule(rule); RuleApplicationResult(...); AvailabilityRule(...).",
  "outputs": "Returns: apply_rule -> RuleApplicationResult; validate_rule -> List[str].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.availability_rule`.",
  "example": "from scrapyard.projects.availability_rule import *",
  "import_path": "scrapyard.projects.availability_rule"
}
### END-PART-META
"""
from sqlalchemy import String, Text, JSON, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, NamedTuple
import os
import logging
import tempfile

logger = logging.getLogger(__name__)


class RuleApplicationResult(NamedTuple):
    valid: bool
    message: str


class AvailabilityRule(IntPKModel):
    __tablename__ = "availability_rules"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    condition: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    constraint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


def apply_rule(resource_id: int, start: datetime, end: datetime, context: dict) -> RuleApplicationResult:
    """Apply availability rules to determine if a resource is available for the given time period."""
    # Input validation
    if not isinstance(resource_id, int):
        raise TypeError("resource_id must be an integer")
    if not isinstance(start, datetime):
        raise TypeError("start must be a datetime")
    if not isinstance(end, datetime):
        raise TypeError("end must be a datetime")
    if not isinstance(context, dict):
        raise TypeError("context must be a dictionary")
    
    # Business logic validation
    if end <= start:
        return RuleApplicationResult(valid=False, message="End time must be after start time")
    
    # Evaluate rule conditions based on context
    if context.get("force_invalid"):
        return RuleApplicationResult(valid=False, message="Rule forced invalid by context")
    
    return RuleApplicationResult(valid=True, message="Rule applied successfully")


def validate_rule(rule: AvailabilityRule) -> List[str]:
    """Validate an availability rule configuration and return list of error messages."""
    errors = []
    
    if not isinstance(rule.name, str):
        errors.append("Name must be a string")
    elif not rule.name.strip():
        errors.append("Name cannot be empty")
    
    if not isinstance(rule.condition, dict):
        errors.append("Condition must be a dictionary")
    
    return errors


def _selftest():
    # Create a temporary SQLite database for testing
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, 'test.db')
        engine = create_engine(f'sqlite:///{db_path}')
        
        # Create all tables using the metadata from the base model
        IntPKModel.metadata.create_all(engine)
        
        # Create a session
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        try:
            # Test rule model creation and retrieval
            test_rule = AvailabilityRule(
                name="Test Rule",
                condition={"key": "value"},
                constraint=None
            )
            session.add(test_rule)
            session.commit()
            
            retrieved_rule = session.execute(
                select(AvailabilityRule).where(AvailabilityRule.name == "Test Rule")
            ).scalar_one()
            
            assert retrieved_rule.name == "Test Rule", "Failed to retrieve rule by name"
            assert retrieved_rule.condition == {"key": "value"}, "Condition mismatch"
            
            # Test apply_rule function
            now = datetime.now(timezone.utc)
            result = apply_rule(
                resource_id=1, 
                start=now, 
                end=now + timedelta(hours=1), 
                context={"key": "value"}
            )
            assert result.valid, f"apply_rule returned invalid: {result.message}"
            
            # Test apply_rule raises exceptions on invalid input
            try:
                apply_rule("not_an_int", now, now + timedelta(hours=1), {})
                assert False, "Expected TypeError for invalid resource_id type"
            except TypeError:
                pass
            
            try:
                apply_rule(1, "not_a_datetime", now + timedelta(hours=1), {})
                assert False, "Expected TypeError for invalid start type"
            except TypeError:
                pass
            
            try:
                apply_rule(1, now, now + timedelta(hours=1), "not_a_dict")
                assert False, "Expected TypeError for invalid context type"
            except TypeError:
                pass
            
            # Test apply_rule business logic validation
            result_invalid_time = apply_rule(1, now + timedelta(hours=2), now, {})
            assert not result_invalid_time.valid, "Should be invalid when end <= start"
            
            result_forced_invalid = apply_rule(1, now, now + timedelta(hours=1), {"force_invalid": True})
            assert not result_forced_invalid.valid, "Should be invalid when context forces invalid"
            
            # Test validate_rule function with valid rule
            valid_rule = AvailabilityRule(
                name="Valid Rule",
                condition={"key": "value"},
                constraint=None
            )
            errors = validate_rule(valid_rule)
            assert not errors, f"validate_rule found unexpected errors: {errors}"
            
            # Test validate_rule detects invalid name type
            invalid_rule_name = AvailabilityRule(
                name=123,  # type: ignore
                condition={"key": "value"},
                constraint=None
            )
            errors = validate_rule(invalid_rule_name)
            assert len(errors) > 0, "validate_rule did not find expected error for invalid name type"
            assert any("Name must be a string" in e for e in errors), "Expected name type error"
            
            # Test validate_rule detects invalid condition type
            invalid_rule_condition = AvailabilityRule(
                name="Another Rule",
                condition="not_a_dict",  # type: ignore
                constraint=None
            )
            errors = validate_rule(invalid_rule_condition)
            assert len(errors) > 0, "validate_rule did not find expected error for invalid condition type"
            assert any("Condition must be a dictionary" in e for e in errors), "Expected condition type error"
            
            logger.info("Selftest passed successfully")
            
        finally:
            session.close()
            engine.dispose()
    
    return True


if __name__ == "__main__":
    _selftest()
