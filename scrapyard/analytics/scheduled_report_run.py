"""
scheduled_report_run - Schedule reports on validated intervals and manage periodic execution state (canonical ScheduledReportRun model).

### PART-META-JSON
{
  "name": "scheduled_report_run",
  "layer": "analytics",
  "purpose": "Schedule reports on validated intervals and manage periodic execution state (canonical ScheduledReportRun model).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "ReportRunScheduler(session).schedule/get_next_run/mark_as_executed; set_default_session(session) + schedule_report(report_id, interval, next_run).",
  "outputs": "ScheduledReportRun rows (table 'scheduled_report_run_scheduled_report_run') - the canonical model imported by analytics/metric_definition.",
  "files_created": [],
  "security_notes": "Intervals are regex/whitelist validated (no cron shell strings executed); timestamps normalized to UTC. Scheduling density is the operational risk - the consumer executing due runs should cap concurrency and per-report frequency.",
  "ai_usage": "Import what you need from `scrapyard.analytics.scheduled_report_run`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.analytics.scheduled_report_run import set_default_session",
  "import_path": "scrapyard.analytics.scheduled_report_run"
}
### END-PART-META
"""
import logging
import re
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import String, DateTime, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# Thread-local storage for default database session
_local = threading.local()


class ScheduledReportRun(IntPKModel):
    """Database model for scheduled report runs."""
    __tablename__ = "scheduled_report_run_scheduled_report_run"
    
    report_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    interval: Mapped[str] = mapped_column(String(50), nullable=False)
    next_run: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )


def _parse_interval(interval: str) -> timedelta:
    """
    Parse interval string into timedelta.
    Supports: hourly, daily, weekly, monthly, minutely, 
    and shorthand like 1h, 2d, 30m, 1w.
    """
    interval = interval.lower().strip()
    
    # Named intervals
    if interval == "hourly":
        return timedelta(hours=1)
    elif interval == "daily":
        return timedelta(days=1)
    elif interval == "weekly":
        return timedelta(weeks=1)
    elif interval == "monthly":
        return timedelta(days=30)
    elif interval == "minutely":
        return timedelta(minutes=1)
    
    # Shorthand format: <number><unit>
    match = re.match(r'^(\d+)([smhdw])$', interval)
    if match:
        value, unit = int(match.group(1)), match.group(2)
        if unit == 's':
            return timedelta(seconds=value)
        elif unit == 'm':
            return timedelta(minutes=value)
        elif unit == 'h':
            return timedelta(hours=value)
        elif unit == 'd':
            return timedelta(days=value)
        elif unit == 'w':
            return timedelta(weeks=value)
    
    raise ValueError(f"Invalid interval format: {interval}. Expected formats: 'hourly', 'daily', '1h', '2d', etc.")


def _ensure_timezone(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _calculate_next_run(interval: str, from_time: Optional[datetime] = None) -> datetime:
    """Calculate next run time based on interval from a given time."""
    if from_time is None:
        from_time = datetime.now(timezone.utc)
    else:
        from_time = _ensure_timezone(from_time)
    
    delta = _parse_interval(interval)
    return from_time + delta


class ReportRunScheduler:
    """Schedules and manages periodic execution of reports."""
    
    def __init__(self, db_session: Session):
        self.db_session = db_session
    
    def schedule(self, report_id: str, interval: str, next_run: datetime) -> None:
        """
        Schedule a report to run at the specified interval starting from next_run.
        """
        # Validate interval
        _parse_interval(interval)  # Raises ValueError if invalid
        
        next_run = _ensure_timezone(next_run)
        now = datetime.now(timezone.utc)
        
        # Check for existing schedule
        stmt = select(ScheduledReportRun).where(ScheduledReportRun.report_id == report_id)
        existing = self.db_session.execute(stmt).scalar_one_or_none()
        
        if existing:
            existing.interval = interval
            existing.next_run = next_run
            existing.status = "pending"
            existing.updated_at = now
            logger.info(f"Updated schedule for report {report_id}")
        else:
            new_run = ScheduledReportRun(
                report_id=report_id,
                interval=interval,
                next_run=next_run,
                status="pending",
                created_at=now,
                updated_at=now
            )
            self.db_session.add(new_run)
            logger.info(f"Created new schedule for report {report_id}")
        
        self.db_session.commit()
    
    def get_next_run(self, report_id: str) -> Optional[datetime]:
        """Get the next scheduled run time for a report."""
        stmt = select(ScheduledReportRun).where(ScheduledReportRun.report_id == report_id)
        result = self.db_session.execute(stmt).scalar_one_or_none()
        if result:
            # Ensure timezone-aware for consistent API (SQLite may return naive)
            return _ensure_timezone(result.next_run)
        return None
    
    def mark_as_executed(self, report_id: str) -> None:
        """
        Mark a report as executed and reschedule for next interval.
        """
        stmt = select(ScheduledReportRun).where(ScheduledReportRun.report_id == report_id)
        result = self.db_session.execute(stmt).scalar_one_or_none()
        
        if not result:
            raise ValueError(f"Report {report_id} not found in scheduler")
        
        now = datetime.now(timezone.utc)
        result.last_run = now
        result.status = "completed"
        
        # Calculate next run based on interval from now
        next_run = _calculate_next_run(result.interval, now)
        result.next_run = next_run
        result.updated_at = now
        
        self.db_session.commit()
        logger.info(f"Report {report_id} executed. Next run scheduled for {next_run}")


def set_default_session(session: Session) -> None:
    """Set the default database session for module-level functions."""
    _local.session = session


def schedule_report(report_id: str, interval: str, next_run: datetime) -> None:
    """
    Module-level convenience function to schedule a report.
    Requires set_default_session() to be called first.
    """
    if not hasattr(_local, 'session') or _local.session is None:
        raise RuntimeError(
            "No default session configured. "
            "Call set_default_session() first or use ReportRunScheduler class directly."
        )
    
    scheduler = ReportRunScheduler(_local.session)
    scheduler.schedule(report_id, interval, next_run)


def _selftest() -> None:
    """Run self-tests to verify module functionality."""
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_scheduled_reports.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        
        SessionFactory = sessionmaker(bind=engine)
        session = SessionFactory()
        
        try:
            # Test 1: Schedule via class
            scheduler = ReportRunScheduler(session)
            now = datetime.now(timezone.utc)
            next_run = now + timedelta(hours=1)
            
            scheduler.schedule("test-report-1", "daily", next_run)
            
            # Verify persistence
            retrieved = scheduler.get_next_run("test-report-1")
            assert retrieved is not None, "Failed to retrieve scheduled run"
            assert abs((retrieved - next_run).total_seconds()) < 1, "Next run time mismatch"
            
            # Test 2: Invalid interval raises ValueError
            try:
                scheduler.schedule("test-invalid", "not_an_interval", next_run)
                assert False, "Should have raised ValueError for invalid interval"
            except ValueError as e:
                assert "Invalid interval" in str(e)
            
            # Test 3: Mark as executed reschedules correctly
            scheduler.mark_as_executed("test-report-1")
            new_next_run = scheduler.get_next_run("test-report-1")
            assert new_next_run is not None
            # Should be approximately 1 day later (daily interval)
            expected_next = now + timedelta(days=1)
            time_diff = abs((new_next_run - expected_next).total_seconds())
            assert time_diff < 5, f"Rescheduled time incorrect: diff={time_diff}s"
            
            # Verify status tracking in DB
            stmt = select(ScheduledReportRun).where(ScheduledReportRun.report_id == "test-report-1")
            record = session.execute(stmt).scalar_one_or_none()
            assert record is not None, "Record should exist in DB"
            assert record.status == "completed", "Status should be completed"
            assert record.last_run is not None, "Last run should be set"
            
            # Test 4: Module-level function with default session
            set_default_session(session)
            future_time = datetime.now(timezone.utc) + timedelta(days=2)
            schedule_report("test-report-module", "hourly", future_time)
            
            retrieved_module = scheduler.get_next_run("test-report-module")
            assert retrieved_module is not None, "Module-level schedule should work"
            
            # Test 5: Invalid usage of module-level function without session
            # Clear the thread-local
            _local.session = None
            try:
                schedule_report("test-fail", "daily", datetime.now(timezone.utc))
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "default session" in str(e).lower() or "configured" in str(e).lower()
            
            # Test 6: Test various interval formats
            test_intervals = ["1h", "30m", "2d", "1w", "60s", "hourly", "daily", "weekly", "minutely", "monthly"]
            for i, interval in enumerate(test_intervals):
                rid = f"test-interval-{i}"
                scheduler.schedule(rid, interval, datetime.now(timezone.utc) + timedelta(hours=1))
                # Verify it was stored
                assert scheduler.get_next_run(rid) is not None
            
            # Test 7: Update existing schedule (reschedule)
            scheduler.schedule("test-report-1", "weekly", datetime.now(timezone.utc) + timedelta(days=7))
            updated = session.execute(select(ScheduledReportRun).where(ScheduledReportRun.report_id == "test-report-1")).scalar_one()
            assert updated.interval == "weekly"
            assert updated.status == "pending"
            
            # Test 8: mark_as_executed raises ValueError for non-existent report
            try:
                scheduler.mark_as_executed("non-existent-report-xyz")
                assert False, "Should have raised ValueError for missing report"
            except ValueError as e:
                assert "not found" in str(e)
            
            logger.info("All self-tests passed")

        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("scheduled_report_run selftest OK")
