"""
timesheet_approver — Manages time tracking approval workflows, enabling timesheets to be submitted, reviewed, and approved by designated supervisors. It ensures proper authorization and maintains an auditable trail of app

### PART-META-JSON
{
  "name": "timesheet_approver",
  "layer": "projects",
  "purpose": "Manages time tracking approval workflows, enabling timesheets to be submitted, reviewed, and approved by designated supervisors. It ensures proper authorization and maintains an auditable trail of app",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: submit_for_approval(session, timesheet_id); approve(session, timesheet_id, approver_id); reject(session, timesheet_id, approver_id, reason); TimesheetApproval(...).",
  "outputs": "Returns: submit_for_approval -> None; approve -> None; reject -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.timesheet_approver`.",
  "example": "from scrapyard.projects.timesheet_approver import *",
  "import_path": "scrapyard.projects.timesheet_approver"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class TimesheetApproval(IntPKModel):
    """ORM model for tracking timesheet approval status and history."""
    
    __tablename__ = "timesheet_approvals"
    
    timesheet_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    approver_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


def submit_for_approval(session: Session, timesheet_id: str) -> None:
    """Submit a timesheet for approval by a manager or supervisor.
    
    Args:
        session: SQLAlchemy session for database operations.
        timesheet_id: Unique identifier for the timesheet.
        
    Raises:
        ValueError: If the timesheet is already submitted for approval.
    """
    existing = session.scalar(
        select(TimesheetApproval).where(TimesheetApproval.timesheet_id == timesheet_id)
    )
    if existing:
        raise ValueError(f"Timesheet {timesheet_id} already submitted for approval")
    
    approval = TimesheetApproval(
        timesheet_id=timesheet_id,
        status="pending"
    )
    session.add(approval)
    session.commit()
    logger.info(f"Timesheet {timesheet_id} submitted for approval")


def approve(session: Session, timesheet_id: str, approver_id: str) -> None:
    """Approve a timesheet and log the action.
    
    Args:
        session: SQLAlchemy session for database operations.
        timesheet_id: Unique identifier for the timesheet.
        approver_id: Identifier of the approving supervisor.
        
    Raises:
        ValueError: If the timesheet is not found or already processed.
    """
    record = session.scalar(
        select(TimesheetApproval).where(TimesheetApproval.timesheet_id == timesheet_id)
    )
    if not record:
        raise ValueError(f"Timesheet {timesheet_id} not found")
    
    if record.status == "approved":
        raise ValueError(f"Timesheet {timesheet_id} is already approved")
    
    record.status = "approved"
    record.approver_id = approver_id
    record.approved_at = datetime.now(timezone.utc)
    session.commit()
    logger.info(f"Timesheet {timesheet_id} approved by {approver_id}")


def reject(session: Session, timesheet_id: str, approver_id: str, reason: Optional[str] = None) -> None:
    """Reject a timesheet and log the action with optional reason.
    
    Args:
        session: SQLAlchemy session for database operations.
        timesheet_id: Unique identifier for the timesheet.
        approver_id: Identifier of the rejecting supervisor.
        reason: Optional reason for rejection.
        
    Raises:
        ValueError: If the timesheet is not found or already processed.
    """
    record = session.scalar(
        select(TimesheetApproval).where(TimesheetApproval.timesheet_id == timesheet_id)
    )
    if not record:
        raise ValueError(f"Timesheet {timesheet_id} not found")
    
    if record.status == "rejected":
        raise ValueError(f"Timesheet {timesheet_id} is already rejected")
    
    record.status = "rejected"
    record.approver_id = approver_id
    record.rejected_at = datetime.now(timezone.utc)
    record.rejection_reason = reason
    session.commit()
    logger.info(f"Timesheet {timesheet_id} rejected by {approver_id}")


def _selftest() -> None:
    """Run offline self-tests using temporary SQLite database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_timesheet.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create all tables
        IntPKModel.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(bind=engine)
        
        with SessionLocal() as session:
            # Test 1: Submitting creates an approval record
            submit_for_approval(session, "ts-1001")
            record = session.scalar(
                select(TimesheetApproval).where(TimesheetApproval.timesheet_id == "ts-1001")
            )
            assert record is not None, "Record should exist after submission"
            assert record.status == "pending", "Status should be pending after submission"
            assert record.approver_id is None, "Approver should be None initially"
            assert record.submitted_at is not None, "Submitted timestamp should be set"
            
            # Test 2: Approving updates the approval status
            approve(session, "ts-1001", "mgr-001")
            session.refresh(record)
            assert record.status == "approved", "Status should be approved"
            assert record.approver_id == "mgr-001", "Approver ID should be set"
            assert record.approved_at is not None, "Approved timestamp should be set"
            
            # Test 3: Rejecting is supported via state flag
            submit_for_approval(session, "ts-1002")
            reject(session, "ts-1002", "mgr-002", "Invalid hours reported")
            record2 = session.scalar(
                select(TimesheetApproval).where(TimesheetApproval.timesheet_id == "ts-1002")
            )
            assert record2.status == "rejected", "Status should be rejected"
            assert record2.rejection_reason == "Invalid hours reported", "Rejection reason should be recorded"
            assert record2.rejected_at is not None, "Rejected timestamp should be set"
            
            # Test 4: ORM model correctly maps to database table
            # Verify table name and columns exist by querying
            all_records = session.scalars(select(TimesheetApproval)).all()
            assert len(all_records) == 2, "Should have two records in database"
            
            # Test 5: Exceptions on invalid input
            # Duplicate submission
            try:
                submit_for_approval(session, "ts-1001")
                assert False, "Should raise ValueError for duplicate submission"
            except ValueError as e:
                assert "already submitted" in str(e)
            
            # Approve non-existent timesheet
            try:
                approve(session, "ts-9999", "mgr-001")
                assert False, "Should raise ValueError for non-existent timesheet"
            except ValueError as e:
                assert "not found" in str(e)
            
            # Reject non-existent timesheet
            try:
                reject(session, "ts-9999", "mgr-001")
                assert False, "Should raise ValueError for non-existent timesheet on reject"
            except ValueError as e:
                assert "not found" in str(e)
            
            # Test double-approve raises error
            try:
                approve(session, "ts-1001", "mgr-003")
                assert False, "Should raise ValueError for already approved timesheet"
            except ValueError as e:
                assert "already approved" in str(e)
        
        # Ensure connections are closed
        engine.dispose()
    
    logger.info("_selftest passed successfully")


if __name__ == "__main__":
    _selftest()
