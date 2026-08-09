"""
clock_rule — Define how time is measured for SLA compliance, enabling flexible and policy-driven time calculations across different service scenarios.

### PART-META-JSON
{
  "name": "clock_rule",
  "layer": "support",
  "purpose": "Define how time is measured for SLA compliance, enabling flexible and policy-driven time calculations across different service scenarios.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: apply_clock_rule(start, end, rule); ClockRuleType(...); ClockRule(...).",
  "outputs": "Returns: apply_clock_rule -> timedelta.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.clock_rule`.",
  "example": "from scrapyard.support.clock_rule import *",
  "import_path": "scrapyard.support.clock_rule"
}
### END-PART-META
"""

from enum import Enum
from datetime import datetime, timedelta
from typing import Dict, Any
from sqlalchemy import String, JSON, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
import os
import tempfile


class ClockRuleType(str, Enum):
    BUSINESS_HOURS = "business_hours"
    FULL_TIME = "full_time"
    CUSTOM = "custom"


class ClockRule(IntPKModel):
    __tablename__ = "clock_rules"
    
    rule_type: Mapped[ClockRuleType] = mapped_column(String(50))
    parameters: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(String(255), default="")


def apply_clock_rule(start: datetime, end: datetime, rule: ClockRule) -> timedelta:
    """Apply the specified clock rule to calculate effective time between start and end."""
    if start > end:
        raise ValueError("Start time must be before or equal to end time")
    
    if rule.rule_type == ClockRuleType.FULL_TIME:
        return end - start
    
    elif rule.rule_type == ClockRuleType.BUSINESS_HOURS:
        params = rule.parameters or {}
        start_hour = params.get("start_hour", 9)
        end_hour = params.get("end_hour", 17)
        work_days = params.get("work_days", [0, 1, 2, 3, 4])
        
        if start_hour >= end_hour:
            raise ValueError("Business hours start_hour must be less than end_hour")
        
        total_seconds = 0
        current = start
        
        while current < end:
            if current.weekday() in work_days:
                day_start = current.replace(hour=start_hour, minute=0, second=0, microsecond=0)
                day_end = current.replace(hour=end_hour, minute=0, second=0, microsecond=0)
                
                if current < day_start:
                    current = day_start
                
                if current < day_end:
                    segment_end = min(end, day_end)
                    if current < segment_end:
                        total_seconds += (segment_end - current).total_seconds()
            
            current = current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        
        return timedelta(seconds=total_seconds)
    
    elif rule.rule_type == ClockRuleType.CUSTOM:
        params = rule.parameters or {}
        interval_seconds = params.get("interval_seconds")
        if interval_seconds is None:
            raise ValueError("CUSTOM rule requires 'interval_seconds' parameter")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        
        raw_duration = (end - start).total_seconds()
        effective_seconds = (raw_duration // interval_seconds) * interval_seconds
        return timedelta(seconds=effective_seconds)
    
    else:
        raise ValueError(f"Unknown rule type: {rule.rule_type}")


def _selftest():
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_clock_rule.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            IntPKModel.metadata.create_all(engine)
            SessionLocal = sessionmaker(bind=engine)
            
            with SessionLocal() as session:
                rule_full = ClockRule(
                    rule_type=ClockRuleType.FULL_TIME,
                    parameters={},
                    description="24/7 operation"
                )
                rule_business = ClockRule(
                    rule_type=ClockRuleType.BUSINESS_HOURS,
                    parameters={"start_hour": 9, "end_hour": 17, "work_days": [0, 1, 2, 3, 4]},
                    description="Weekdays 9-5"
                )
                rule_custom = ClockRule(
                    rule_type=ClockRuleType.CUSTOM,
                    parameters={"interval_seconds": 3600},
                    description="Hourly billing"
                )
                
                session.add(rule_full)
                session.add(rule_business)
                session.add(rule_custom)
                session.commit()
                
                assert rule_full.id is not None
                assert rule_business.id is not None
                assert rule_custom.id is not None
                
                retrieved_full = session.get(ClockRule, rule_full.id)
                assert retrieved_full is not None
                assert retrieved_full.rule_type == ClockRuleType.FULL_TIME
                assert retrieved_full.description == "24/7 operation"
                
                start = datetime(2023, 6, 1, 10, 0, 0)
                end = datetime(2023, 6, 1, 15, 30, 0)
                result = apply_clock_rule(start, end, rule_full)
                assert result == timedelta(hours=5, minutes=30)
                
                monday_morning = datetime(2023, 6, 5, 10, 0, 0)
                tuesday_morning = datetime(2023, 6, 6, 10, 0, 0)
                result = apply_clock_rule(monday_morning, tuesday_morning, rule_business)
                assert result == timedelta(hours=8)
                
                start = datetime(2023, 6, 1, 9, 0, 0)
                end = datetime(2023, 6, 1, 12, 30, 0)
                result = apply_clock_rule(start, end, rule_custom)
                assert result == timedelta(seconds=10800)
                
                try:
                    apply_clock_rule(end, start, rule_full)
                    assert False, "Should raise ValueError"
                except ValueError:
                    pass
                
                bad_custom = ClockRule(
                    rule_type=ClockRuleType.CUSTOM,
                    parameters={},
                    description="Bad custom"
                )
                try:
                    apply_clock_rule(start, end, bad_custom)
                    assert False, "Should raise ValueError"
                except ValueError:
                    pass
                
                bad_custom2 = ClockRule(
                    rule_type=ClockRuleType.CUSTOM,
                    parameters={"interval_seconds": -1},
                    description="Bad custom 2"
                )
                try:
                    apply_clock_rule(start, end, bad_custom2)
                    assert False, "Should raise ValueError"
                except ValueError:
                    pass
                
                bad_business = ClockRule(
                    rule_type=ClockRuleType.BUSINESS_HOURS,
                    parameters={"start_hour": 17, "end_hour": 9},
                    description="Bad hours"
                )
                try:
                    apply_clock_rule(start, end, bad_business)
                    assert False, "Should raise ValueError"
                except ValueError:
                    pass
                
                rule_id = rule_full.id
                session.delete(rule_full)
                session.commit()
                deleted = session.get(ClockRule, rule_id)
                assert deleted is None
                
                remaining = session.execute(select(ClockRule)).scalars().all()
                assert len(remaining) == 2
                
        finally:
            engine.dispose()
            try:
                os.unlink(db_path)
            except OSError:
                pass


if __name__ == "__main__":
    _selftest()
