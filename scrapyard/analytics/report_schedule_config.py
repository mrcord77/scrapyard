"""
report_schedule_config - Configure report scheduling with cron expressions and timezones.

### PART-META-JSON
{
  "name": "report_schedule_config",
  "layer": "analytics",
  "purpose": "Configure report scheduling with cron expressions and timezones.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure_report_schedule(report_id, cron_expression, timezone).",
  "outputs": "ReportScheduleConfigModel rows with validated cron/timezone.",
  "files_created": [],
  "security_notes": "Cron expressions are validated by pattern, never executed as shell input; timezones validated against known names. Scheduling density is the operational risk - cap per-report frequency in the scheduler consuming these rows.",
  "ai_usage": "Import what you need from `scrapyard.analytics.report_schedule_config`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.analytics.report_schedule_config import configure_report_schedule",
  "import_path": "scrapyard.analytics.report_schedule_config"
}
### END-PART-META
"""
import logging
import os
import re
import tempfile
from datetime import datetime

from sqlalchemy import String, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    _HAS_ZONEINFO = True
except ImportError:
    _HAS_ZONEINFO = False


class ReportScheduleConfigModel(IntPKModel):
    """Database model for report schedule configurations."""
    
    __tablename__ = "report_schedule_config"
    
    report_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    cron_expression: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="UTC")


def _validate_cron_expression(cron_expr: str) -> None:
    """Validate cron expression has exactly 5 fields."""
    if not cron_expr or not isinstance(cron_expr, str):
        raise ValueError("Cron expression must be a non-empty string")
    
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must have exactly 5 fields, got {len(parts)}: {cron_expr}")
    
    pattern = re.compile(r'^[\d\*\,\-\/\?]+$')
    for i, part in enumerate(parts):
        if not pattern.match(part):
            raise ValueError(f"Invalid characters in cron field {i+1}: '{part}'")
        if part not in ['*', '?']:
            check_part = part.split('/')[0] if '/' in part else part
            for sub in check_part.split(','):
                if sub in ['*', '?']:
                    continue
                if '-' in sub:
                    bounds = sub.split('-')
                    if len(bounds) != 2 or not bounds[0].isdigit() or not bounds[1].isdigit():
                        raise ValueError(f"Invalid range in cron field {i+1}: '{part}'")
                elif not sub.isdigit():
                    raise ValueError(f"Invalid value in cron field {i+1}: '{part}'")


def _validate_timezone(tz_str: str) -> None:
    """Validate timezone string."""
    if not tz_str or not isinstance(tz_str, str):
        raise ValueError("Timezone must be a non-empty string")
    if _HAS_ZONEINFO:
        try:
            ZoneInfo(tz_str)
        except Exception as e:
            raise ValueError(f"Invalid timezone: {tz_str}") from e


def configure_report_schedule(
    report_id: str, 
    cron_expression: str, 
    timezone: str
) -> ReportScheduleConfigModel:
    """Configure a report schedule with cron expression and timezone.
    
    Args:
        report_id: Unique identifier for the report
        cron_expression: Standard cron expression (5 fields)
        timezone: IANA timezone name
        
    Returns:
        ReportScheduleConfigModel instance
        
    Raises:
        ValueError: If inputs are invalid
    """
    if not report_id or not isinstance(report_id, str):
        raise ValueError("report_id must be a non-empty string")
    
    _validate_cron_expression(cron_expression)
    _validate_timezone(timezone)
    
    return ReportScheduleConfigModel(
        report_id=report_id,
        cron_expression=cron_expression,
        timezone=timezone
    )


def _selftest():
    """Module self-test."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        ReportScheduleConfigModel.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        try:
            # Configure and retrieve
            config1 = configure_report_schedule("rpt-001", "0 9 * * 1", "UTC")
            session.add(config1)
            session.commit()
            
            retrieved = session.execute(
                select(ReportScheduleConfigModel).where(
                    ReportScheduleConfigModel.report_id == "rpt-001"
                )
            ).scalar_one()
            assert retrieved.cron_expression == "0 9 * * 1"
            assert retrieved.timezone == "UTC"
            
            # Validate invalid cron
            try:
                configure_report_schedule("rpt-bad", "invalid cron", "UTC")
                assert False, "Should raise ValueError"
            except ValueError:
                pass
            
            try:
                configure_report_schedule("rpt-bad", "0 9 * *", "UTC")
                assert False, "Should raise for 4 fields"
            except ValueError:
                pass
            
            # Timezone handling
            config2 = configure_report_schedule("rpt-002", "30 14 * * *", "America/New_York")
            session.add(config2)
            session.commit()
            
            result2 = session.execute(
                select(ReportScheduleConfigModel).where(
                    ReportScheduleConfigModel.report_id == "rpt-002"
                )
            ).scalar_one()
            assert result2.timezone == "America/New_York"
            
            if _HAS_ZONEINFO:
                tz = ZoneInfo(result2.timezone)
                assert datetime.now(tz).tzinfo is not None
            
            # Query by report_id
            configs = session.execute(
                select(ReportScheduleConfigModel).where(
                    ReportScheduleConfigModel.report_id == "rpt-001"
                )
            ).scalars().all()
            assert len(configs) == 1
            assert configs[0].report_id == "rpt-001"
            
            # Flush without commit
            config3 = configure_report_schedule("rpt-003", "0 0 * * *", "Europe/London")
            session.add(config3)
            session.flush()
            
            flushed = session.execute(
                select(ReportScheduleConfigModel).where(
                    ReportScheduleConfigModel.report_id == "rpt-003"
                )
            ).scalar_one()
            assert flushed.id is not None
            session.rollback()
            
            # Type hints verification
            assert isinstance(config3, ReportScheduleConfigModel)
            assert isinstance(config3.report_id, str)
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
