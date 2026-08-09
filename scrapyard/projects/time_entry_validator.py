"""
time_entry_validator — ** The `time_entry_validator` module enforces business rules on time tracking data to ensure accuracy and compliance with organizational policies. It provides reusable validation logic for timers and 

### PART-META-JSON
{
  "name": "time_entry_validator",
  "layer": "projects",
  "purpose": "Enforces business rules on time tracking data to ensure accuracy and compliance with organizational policies. It provides reusable validation logic for timers and.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: validate_timer(timer); validate_timesheet(timesheet); Timer(...); Timesheet(...); ValidationError(...) (plus more).",
  "outputs": "Returns: validate_timer -> List[ValidationError]; validate_timesheet -> List[ValidationError].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.time_entry_validator`.",
  "example": "from scrapyard.projects.time_entry_validator import *",
  "import_path": "scrapyard.projects.time_entry_validator"
}
### END-PART-META
"""
from sqlalchemy import String, Text, JSON, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import os
import logging
import tempfile

logger = logging.getLogger(__name__)


@dataclass
class Timer:
    id: int
    project_id: int
    duration: float
    start_time: datetime
    end_time: Optional[datetime] = None


@dataclass
class Timesheet:
    id: int
    user_id: int
    period_start: datetime
    period_end: datetime
    entries: List[Timer] = field(default_factory=list)


class ValidationError(Exception):
    pass


class ValidationRule(IntPKModel):
    __tablename__ = 'validation_rules'

    rule_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    condition: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)


def validate_timer(timer: Timer) -> List[ValidationError]:
    errors = []
    
    # Validate non-negative duration
    if timer.duration < 0:
        errors.append(ValidationError("Duration cannot be negative"))
    
    # Validate project association (project_id must be positive)
    if timer.project_id <= 0:
        errors.append(ValidationError("Invalid project association"))
    
    # Validate time range consistency if end_time is provided
    if timer.end_time is not None and timer.end_time < timer.start_time:
        errors.append(ValidationError("End time cannot be before start time"))
    
    return errors


def validate_timesheet(timesheet: Timesheet) -> List[ValidationError]:
    errors = []
    
    # Validate period consistency
    if timesheet.period_end < timesheet.period_start:
        errors.append(ValidationError("Period end cannot be before period start"))
    
    # Aggregate all timers in the timesheet
    for entry in timesheet.entries:
        timer_errors = validate_timer(entry)
        errors.extend(timer_errors)
    
    return errors


def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        
        # Create SQLite database for testing
        engine = create_engine(f'sqlite:///{db_path}')
        IntPKModel.metadata.create_all(engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        
        try:
            # Test ValidationRule creation, query, and deletion
            with SessionLocal() as session:
                rule = ValidationRule(
                    rule_name='NonNegativeDuration', 
                    description='Duration must be non-negative', 
                    condition={'type': 'duration', 'op': '>=', 'value': 0}
                )
                session.add(rule)
                session.commit()
                
                # Query to verify creation
                stmt = select(ValidationRule).where(ValidationRule.rule_name == 'NonNegativeDuration')
                result = session.execute(stmt).scalar_one_or_none()
                assert result is not None, "ValidationRule should be queryable"
                assert result.description == 'Duration must be non-negative'
                
                # Delete to verify deletion
                session.delete(result)
                session.commit()
                
                # Verify deletion
                result_after = session.execute(stmt).scalar_one_or_none()
                assert result_after is None, "ValidationRule should be deletable"
            
            # Test timer validation
            now = datetime.now(timezone.utc)
            valid_timer = Timer(id=1, project_id=1, duration=2.5, start_time=now)
            invalid_timer = Timer(id=2, project_id=1, duration=-1.0, start_time=now)
            
            assert not validate_timer(valid_timer), "Valid timer should return no errors"
            assert len(validate_timer(invalid_timer)) > 0, "Invalid timer should return errors"
            
            # Test timesheet validation
            valid_timesheet = Timesheet(
                id=1, 
                user_id=1, 
                period_start=now - timedelta(days=7), 
                period_end=now,
                entries=[valid_timer]
            )
            invalid_timesheet = Timesheet(
                id=2, 
                user_id=1, 
                period_start=now, 
                period_end=now - timedelta(days=8),
                entries=[]
            )
            
            assert not validate_timesheet(valid_timesheet), "Valid timesheet should return no errors"
            assert len(validate_timesheet(invalid_timesheet)) > 0, "Invalid timesheet should return errors"
            
        finally:
            # Cleanup
            engine.dispose()


if __name__ == "__main__":
    _selftest()
