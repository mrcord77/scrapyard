"""
report_run_history - Log and query the execution history of report runs.

### PART-META-JSON
{
  "name": "report_run_history",
  "layer": "analytics",
  "purpose": "Log and query the execution history of report runs.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure(engine); log_report_run(report_id, status, output).",
  "outputs": "ReportRunHistoryModel rows with status and output per run.",
  "files_created": [],
  "security_notes": "Append-only run log for observability. Output blobs may embed report data - cap their size and treat stored output as sensitive as the report itself.",
  "ai_usage": "Import what you need from `scrapyard.analytics.report_run_history`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.analytics.report_run_history import configure",
  "import_path": "scrapyard.analytics.report_run_history"
}
### END-PART-META
"""
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, String, Text, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

_engine: Optional[Any] = None


def configure(engine: Optional[Any]) -> None:
    """Configure the module with a SQLAlchemy engine."""
    global _engine
    _engine = engine


class ReportRunHistoryModel(IntPKModel):
    """ORM model for tracking report execution history."""
    __tablename__ = "report_run_history"

    report_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


def log_report_run(report_id: str, status: str, output: str) -> None:
    """Log a report run with status and output to the database."""
    if not isinstance(report_id, str):
        raise TypeError(f"report_id must be str, got {type(report_id)}")
    if not isinstance(status, str):
        raise TypeError(f"status must be str, got {type(status)}")
    if not isinstance(output, str):
        raise TypeError(f"output must be str, got {type(output)}")
    
    if _engine is None:
        raise RuntimeError("Database engine not configured. Call configure() first.")
    
    with Session(_engine) as session:
        with session.begin():
            record = ReportRunHistoryModel(
                report_id=report_id,
                status=status,
                output=output,
                created_at=datetime.now(timezone.utc),
            )
            session.add(record)


def _selftest() -> None:
    """Self-contained test suite using temporary SQLite."""
    import tempfile
    
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_history.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Configure module for testing
        configure(engine)
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        
        # Test 1: Logging creates a new record
        log_report_run("report-abc-123", "success", "Completed successfully")
        
        # Verify record exists using select()
        with Session(engine) as session:
            stmt = select(ReportRunHistoryModel).where(
                ReportRunHistoryModel.report_id == "report-abc-123"
            )
            result = session.execute(stmt).scalar_one_or_none()
            assert result is not None, "Record should be created"
            assert result.status == "success"
            assert result.output == "Completed successfully"
            assert result.created_at is not None
        
        # Test 2: Can query and filter by report_id and status
        log_report_run("report-xyz-999", "failed", "Error occurred")
        log_report_run("report-abc-123", "running", "In progress")
        
        with Session(engine) as session:
            # Filter by status
            stmt_status = select(ReportRunHistoryModel).where(
                ReportRunHistoryModel.status == "failed"
            )
            failed_runs = session.execute(stmt_status).scalars().all()
            assert len(failed_runs) == 1
            assert failed_runs[0].report_id == "report-xyz-999"
            
            # Filter by report_id
            stmt_report = select(ReportRunHistoryModel).where(
                ReportRunHistoryModel.report_id == "report-abc-123"
            )
            specific_reports = session.execute(stmt_report).scalars().all()
            assert len(specific_reports) == 2  # One success, one running
        
        # Test 3: Type safety - appropriate errors
        try:
            log_report_run(123, "status", "output")  # type: ignore
            assert False, "Should raise TypeError for non-string report_id"
        except TypeError:
            pass
        
        try:
            log_report_run("id", 123, "output")  # type: ignore
            assert False, "Should raise TypeError for non-string status"
        except TypeError:
            pass
        
        try:
            log_report_run("id", "status", 123)  # type: ignore
            assert False, "Should raise TypeError for non-string output"
        except TypeError:
            pass
        
        # Test 4: Runtime error when not configured
        configure(None)
        try:
            log_report_run("x", "y", "z")
            assert False, "Should raise RuntimeError when engine not configured"
        except RuntimeError:
            pass
        
        # Cleanup
        engine.dispose()
    
    elapsed = time.time() - start_time
    assert elapsed < 20, f"Selftest took {elapsed}s, must be under 20s"
    logger.info(f"_selftest passed in {elapsed:.2f}s")


if __name__ == "__main__":
    _selftest()
    print("report_run_history selftest OK")
