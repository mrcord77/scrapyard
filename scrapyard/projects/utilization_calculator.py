"""
utilization_calculator — ** Calculates user utilization rates based on billable and available time, enabling accurate resource planning and performance tracking. Designed as a reusable, testable, and self-contained module for

### PART-META-JSON
{
  "name": "utilization_calculator",
  "layer": "projects",
  "purpose": "Calculates user utilization rates based on billable and available time, enabling accurate resource planning and performance tracking. Designed as a reusable, testable, and self-contained module for.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure_session_factory(factory); calculate_user_utilization(user_id, period); UtilizationReport(...).",
  "outputs": "Returns: configure_session_factory -> None; calculate_user_utilization -> float.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.utilization_calculator`.",
  "example": "from scrapyard.projects.utilization_calculator import *",
  "import_path": "scrapyard.projects.utilization_calculator"
}
### END-PART-META
"""
from sqlalchemy import String, Float, DateTime, func, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from typing import Optional, Callable
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

# Module-level session factory for dependency injection (configured by _selftest or caller)
_session_factory: Optional[Callable[[], Session]] = None

def configure_session_factory(factory: Optional[Callable[[], Session]]) -> None:
    """Configure the session factory for database operations."""
    global _session_factory
    _session_factory = factory

class UtilizationReport(IntPKModel):
    __tablename__ = "utilization_reports"
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    period: Mapped[str] = mapped_column(String(50), nullable=False)
    billable_time: Mapped[float] = mapped_column(Float(), default=0.0)
    available_time: Mapped[float] = mapped_column(Float(), default=0.0)
    utilization_rate: Mapped[float] = mapped_column(Float(), default=0.0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(),
        nullable=False
    )

def calculate_user_utilization(user_id: str, period: str) -> float:
    """Calculate the utilization rate for a given user and time period."""
    if _session_factory is None:
        raise RuntimeError("Session factory not configured. Call configure_session_factory first.")
    
    session = _session_factory()
    try:
        # Query for existing reports for this user and period
        stmt = select(UtilizationReport).where(
            UtilizationReport.user_id == user_id,
            UtilizationReport.period == period
        )
        results = session.execute(stmt).scalars().all()
        
        if not results:
            logger.warning(f"No utilization data found for user {user_id} in period {period}")
            return 0.0
        
        # Aggregate times (supporting multiple entries per user/period)
        total_billable = sum(r.billable_time for r in results)
        total_available = sum(r.available_time for r in results)
        
        # Calculate utilization rate
        if total_available > 0:
            utilization_rate = (total_billable / total_available) * 100.0
        else:
            utilization_rate = 0.0
        
        # Update stored utilization rates
        for report in results:
            report.utilization_rate = utilization_rate
        
        session.commit()
        logger.info(f"Calculated utilization for {user_id}/{period}: {utilization_rate:.2f}%")
        return utilization_rate
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error calculating utilization for {user_id}/{period}: {e}")
        raise
    finally:
        session.close()

def _selftest():
    """Self-test the module with a temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
        db_path = os.path.join(tempdir, 'utilization_calculator.db')
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create session factory bound to test engine
        TestSession = sessionmaker(bind=engine, expire_on_commit=False)
        configure_session_factory(TestSession)
        
        # Create tables
        UtilizationReport.metadata.create_all(engine)
        
        # Test data insertion
        test_data = [
            {"user_id": "user1", "period": "month", "billable_time": 40.0, "available_time": 50.0},
            {"user_id": "user2", "period": "quarter", "billable_time": 80.0, "available_time": 100.0}
        ]
        
        with TestSession() as session:
            for data in test_data:
                report = UtilizationReport(
                    user_id=data["user_id"],
                    period=data["period"],
                    billable_time=data["billable_time"],
                    available_time=data["available_time"]
                )
                session.add(report)
            session.commit()
        
        # Test calculation returns correct rate
        utilization_rate_user1_month = calculate_user_utilization("user1", "month")
        assert abs(utilization_rate_user1_month - 80.0) < 0.001, f"Expected 80.0, got {utilization_rate_user1_month}"
        
        utilization_rate_user2_quarter = calculate_user_utilization("user2", "quarter")
        assert abs(utilization_rate_user2_quarter - 80.0) < 0.001, f"Expected 80.0, got {utilization_rate_user2_quarter}"
        
        # Test that rates are persisted in database
        with TestSession() as session:
            report = session.execute(
                select(UtilizationReport).where(
                    UtilizationReport.user_id == "user1",
                    UtilizationReport.period == "month"
                )
            ).scalar_one()
            
            assert abs(report.utilization_rate - 80.0) < 0.001, f"Expected stored rate 80.0, got {report.utilization_rate}"
            assert report.billable_time == 40.0
            assert report.available_time == 50.0
            assert isinstance(report.timestamp, datetime)
        
        logger.info("All self-tests passed successfully")

if __name__ == "__main__":
    _selftest()
