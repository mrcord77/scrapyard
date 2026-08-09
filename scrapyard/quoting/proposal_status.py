"""
proposal_status - Validated proposal status state machine with per-transition history.

### PART-META-JSON
{
  "name": "proposal_status",
  "layer": "quoting",
  "purpose": "Validated proposal status state machine with per-transition history.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure(engine); is_status_valid(current, new); change_status(proposal_id, new_status, user_id); get_status_history(proposal_id).",
  "outputs": "ProposalStatus rows plus history entries per transition.",
  "files_created": [],
  "security_notes": "Transitions are whitelist-validated (no arbitrary jumps) and history is append-only with actor user_id recorded. user_id is trusted from the caller - authenticate upstream.",
  "ai_usage": "Import what you need from `scrapyard.quoting.proposal_status`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.quoting.proposal_status import configure",
  "import_path": "scrapyard.quoting.proposal_status"
}
### END-PART-META
"""
import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Integer, String, create_engine, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# Valid state transitions for the proposal lifecycle finite state machine
VALID_TRANSITIONS: Dict[str, List[str]] = {
    "draft": ["submitted", "cancelled"],
    "submitted": ["under_review", "approved", "rejected", "cancelled"],
    "under_review": ["approved", "rejected", "cancelled", "submitted"],
    "approved": [],
    "rejected": [],
    "cancelled": [],
}

# Module-level database configuration (set via configure())
_engine: Optional[Any] = None
_Session: Optional[Any] = None


def configure(engine: Any) -> None:
    """Configure the module to use the provided SQLAlchemy engine."""
    global _engine, _Session
    _engine = engine
    _Session = sessionmaker(bind=engine)


def _get_session() -> Session:
    """Get a configured session or raise RuntimeError."""
    if _Session is None:
        raise RuntimeError("Database not configured. Call configure(engine) first.")
    return _Session()


class ProposalStatus(IntPKModel):
    """Stores status transitions with timestamps and user context."""

    __tablename__ = "proposal_statuses"

    proposal_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    changed_by: Mapped[int] = mapped_column(Integer, nullable=False)


def is_status_valid(current_status: str, new_status: str) -> bool:
    """Check if transitioning from current_status to new_status is valid."""
    allowed = VALID_TRANSITIONS.get(current_status, [])
    return new_status in allowed


def _get_current_status(session: Session, proposal_id: int) -> str:
    """Get the current status for a proposal, defaulting to 'draft'."""
    stmt = (
        select(ProposalStatus)
        .where(ProposalStatus.proposal_id == proposal_id)
        .order_by(ProposalStatus.changed_at.desc())
        .limit(1)
    )
    result = session.execute(stmt).scalar_one_or_none()
    if result is None:
        return "draft"
    return result.status


def change_status(proposal_id: int, new_status: str, user_id: int) -> None:
    """
    Transition a proposal to a new status.
    
    Raises:
        ValueError: If the transition is not allowed.
    """
    session = _get_session()
    try:
        current = _get_current_status(session, proposal_id)

        if not is_status_valid(current, new_status):
            raise ValueError(
                f"Invalid transition from '{current}' to '{new_status}'"
            )

        record = ProposalStatus(
            proposal_id=proposal_id,
            status=new_status,
            previous_status=current,
            changed_by=user_id,
        )
        session.add(record)
        session.commit()
        logger.debug(
            f"Proposal {proposal_id}: {current} -> {new_status} by user {user_id}"
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_status_history(proposal_id: int) -> List[Dict[str, Any]]:
    """Return chronological history of status changes for a proposal."""
    session = _get_session()
    try:
        stmt = (
            select(ProposalStatus)
            .where(ProposalStatus.proposal_id == proposal_id)
            .order_by(ProposalStatus.changed_at.asc())
        )
        results = session.execute(stmt).scalars().all()

        return [
            {
                "id": r.id,
                "proposal_id": r.proposal_id,
                "status": r.status,
                "previous_status": r.previous_status,
                "changed_at": r.changed_at,
                "changed_by": r.changed_by,
            }
            for r in results
        ]
    finally:
        session.close()


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        configure(engine)
        IntPKModel.metadata.create_all(engine)

        # Test: Initial status is 'draft' by default (implicit)
        # Test: Valid transition draft -> submitted
        change_status(proposal_id=1, new_status="submitted", user_id=100)
        
        history = get_status_history(1)
        assert len(history) == 1, f"Expected 1 record, got {len(history)}"
        assert history[0]["status"] == "submitted"
        assert history[0]["previous_status"] == "draft"
        assert history[0]["changed_by"] == 100
        assert isinstance(history[0]["changed_at"], datetime)
        
        # Test: Invalid transition submitted -> draft raises error
        try:
            change_status(proposal_id=1, new_status="draft", user_id=101)
            raise AssertionError("Expected ValueError for invalid transition")
        except ValueError as e:
            assert "Invalid transition" in str(e)
        
        # Verify history unchanged after failed transition
        history = get_status_history(1)
        assert len(history) == 1, "History should not record failed transitions"
        
        # Test: is_status_valid pure function
        assert is_status_valid("draft", "submitted") is True
        assert is_status_valid("submitted", "draft") is False
        assert is_status_valid("submitted", "under_review") is True
        assert is_status_valid("approved", "submitted") is False
        
        # Test: Additional valid transition
        change_status(proposal_id=1, new_status="under_review", user_id=102)
        history = get_status_history(1)
        assert len(history) == 2
        assert history[1]["status"] == "under_review"
        assert history[1]["previous_status"] == "submitted"
        
        # Test: New proposal starts fresh with draft default
        change_status(proposal_id=2, new_status="submitted", user_id=200)
        history2 = get_status_history(2)
        assert len(history2) == 1
        assert history2[0]["previous_status"] == "draft"
        
        logger.info("proposal_status self-test passed")


if __name__ == "__main__":
    _selftest()
    print("proposal_status selftest OK")
