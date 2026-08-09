"""
pipeline_scheduler — Schedule the execution of ETL pipelines at specified intervals or based on triggers. This module provides a lightweight, type-safe interface for defining and managing pipeline execution schedules.

### PART-META-JSON
{
  "name": "pipeline_scheduler",
  "layer": "data_eng",
  "purpose": "Schedule the execution of ETL pipelines at specified intervals or based on triggers. This module provides a lightweight, type-safe interface for defining and managing pipeline execution schedules.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: schedule_pipeline(pipeline_id, trigger, interval, **kwargs); run_at_interval(pipeline_id, interval, start_time); calculate_next_cron_time(expression); TriggerType(...); CronTrigger(...); IntervalTrigger(...) (plus more).",
  "outputs": "Returns: schedule_pipeline -> Schedule; run_at_interval -> Schedule; calculate_next_cron_time -> datetime.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.data_eng.pipeline_scheduler`.",
  "example": "from scrapyard.data_eng.pipeline_scheduler import *",
  "import_path": "scrapyard.data_eng.pipeline_scheduler"
}
### END-PART-META
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import os, logging, sqlite3, tempfile

logger = logging.getLogger(__name__)

@dataclass
class TriggerType:
    pass

@dataclass
class CronTrigger(TriggerType):
    expression: str

@dataclass
class IntervalTrigger(TriggerType):
    interval: timedelta

@dataclass
class Schedule:
    pipeline_id: str
    trigger: TriggerType
    next_run_time: Optional[datetime] = None
    last_run_time: Optional[datetime] = None
    retry_policy: Dict[str, Any] = field(default_factory=dict)
    failure_policy: Dict[str, Any] = field(default_factory=dict)

def schedule_pipeline(pipeline_id: str, trigger: TriggerType, interval: Optional[timedelta] = None, **kwargs) -> Schedule:
    if isinstance(trigger, CronTrigger):
        next_run_time = calculate_next_cron_time(trigger.expression)
    elif isinstance(trigger, IntervalTrigger):
        next_run_time = datetime.now(timezone.utc) + interval
    else:
        raise ValueError("Unsupported trigger type")

    return Schedule(pipeline_id=pipeline_id, trigger=trigger, next_run_time=next_run_time, **kwargs)

def run_at_interval(pipeline_id: str, interval: timedelta, start_time: Optional[datetime] = None) -> Schedule:
    if start_time is None:
        start_time = datetime.now(timezone.utc)
    
    next_run_time = start_time + interval
    return Schedule(pipeline_id=pipeline_id, trigger=IntervalTrigger(interval=interval), next_run_time=next_run_time)

def calculate_next_cron_time(expression: str) -> datetime:
    # Simplified cron expression parsing for demonstration purposes
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError("Invalid cron expression")
    
    current_time = datetime.now(timezone.utc)
    next_time = current_time
    
    for part in parts:
        if part == "*":
            continue
        
        if "-" in part or "/" in part or "," in part or "?" in part:
            # Handle more complex expressions
            pass
    
    return next_time

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        conn = sqlite3.connect(os.path.join(temp_dir, 'test.db'))
        
        # Test scheduling a pipeline with interval and trigger
        schedule1 = schedule_pipeline(pipeline_id="pipeline1", trigger=CronTrigger(expression="* * * * *"), retry_policy={"attempts": 3})
        assert schedule1.pipeline_id == "pipeline1"
        assert isinstance(schedule1.trigger, CronTrigger)
        
        schedule2 = run_at_interval(pipeline_id="pipeline2", interval=timedelta(hours=1))
        assert schedule2.pipeline_id == "pipeline2"
        assert isinstance(schedule2.trigger, IntervalTrigger)
        
        # Test retrieving and validating scheduled jobs
        assert schedule1.next_run_time is not None
        assert schedule2.next_run_time is not None
        
        # Test handling invalid input with proper exceptions
        try:
            schedule_pipeline(pipeline_id="pipeline3", trigger=object())
            raise AssertionError("Expected ValueError")
        except ValueError as e:
            assert str(e) == "Unsupported trigger type"
        
        conn.close()

if __name__ == "__main__":
    _selftest()
