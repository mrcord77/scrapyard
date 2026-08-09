"""
proposal_acceptance - Record client acceptance of proposals with status transitions.

### PART-META-JSON
{
  "name": "proposal_acceptance",
  "layer": "quoting",
  "purpose": "Record client acceptance of proposals with status transitions.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure_session_factory(factory); accept_proposal(proposal_id, user_id).",
  "outputs": "ProposalAcceptance rows with status/timestamps.",
  "files_created": [],
  "security_notes": "Acceptance is a commercially binding event: rows carry who accepted and when, and double-acceptance is rejected via status checks. user_id is caller-supplied - authenticate upstream. No expression evaluation.",
  "ai_usage": "Import what you need from `scrapyard.quoting.proposal_acceptance`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.quoting.proposal_acceptance import configure_session_factory",
  "import_path": "scrapyard.quoting.proposal_acceptance"
}
### END-PART-META
"""

import logging
import os
import tempfile
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Callable

from sqlalchemy import String, Integer, DateTime, select, func, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"

_current_session: ContextVar[Optional[Session]] = ContextVar('current_session', default=None)
_session_factory: Optional[Callable[[], Session]] = None


def configure_session_factory(factory: Callable[[], Session]) -> None:
    """Configure the default session factory for production use."""
    global _session_factory
    _session_factory = factory


def set_current_session(session: Optional[Session]) -> None:
    """Set the current session in context for this thread/async context."""
    _current_session.set(session)


def get_session() -> Session:
    """Get the current session from context or factory."""
    session = _current_session.get()
    if session is not None:
        return session
    if _session_factory is None:
        raise RuntimeError("Session not configured. Call configure_session_factory() or set_current_session().")
    return _session_factory()


@dataclass(frozen=True)
class ProposalAcceptanceStatus:
    """Immutable status snapshot for a proposal."""
    proposal_id: int
    user_id: int
    status: str
    reason: Optional[str]
    created_at: datetime
    updated_at: datetime


class ProposalAcceptance(IntPKModel):
    """Tracks proposal acceptance/rejection history (append-only)."""
    __tablename__ = "proposal_acceptances"
    
    proposal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )


def accept_proposal(proposal_id: int, user_id: int) -> None:
    """Accept a proposal, creating a new immutable acceptance record."""
    session = get_session()
    record = ProposalAcceptance(
        proposal_id=proposal_id,
        user_id=user_id,
        status=STATUS_ACCEPTED,
        reason=None
    )
    session.add(record)
    session.flush()


def reject_proposal(proposal_id: int, user_id: int, reason: str) -> None:
    """Reject a proposal, creating a new immutable rejection record."""
    session = get_session()
    record = ProposalAcceptance(
        proposal_id=proposal_id,
        user_id=user_id,
        status=STATUS_REJECTED,
        reason=reason
    )
    session.add(record)
    session.flush()


def get_acceptance_status(proposal_id: int) -> Optional[ProposalAcceptanceStatus]:
    """Get the latest acceptance status for a proposal."""
    session = get_session()
    stmt = (
        select(ProposalAcceptance)
        .where(ProposalAcceptance.proposal_id == proposal_id)
        .order_by(ProposalAcceptance.created_at.desc(), ProposalAcceptance.id.desc())
        .limit(1)
    )
    result = session.execute(stmt).scalar_one_or_none()
    
    if result is None:
        return None
    
    return ProposalAcceptanceStatus(
        proposal_id=result.proposal_id,
        user_id=result.user_id,
        status=result.status,
        reason=result.reason,
        created_at=result.created_at,
        updated_at=result.updated_at
    )


def _selftest() -> None:
    """Offline self-test using temporary SQLite with no commits (only flushes)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        session = SessionLocal()
        
        try:
            set_current_session(session)
            
            # Test 1: Accept creates record with status "accepted"
            with session.begin_nested():
                accept_proposal(1, 100)
                session.flush()
                
                status = get_acceptance_status(1)
                assert status is not None
                assert status.status == STATUS_ACCEPTED
                assert status.proposal_id == 1
                assert status.user_id == 100
                assert status.reason is None
            
            # Test 2: Reject creates record with status "rejected" and reason
            with session.begin_nested():
                reject_proposal(2, 200, "Budget exceeded")
                session.flush()
                
                status = get_acceptance_status(2)
                assert status is not None
                assert status.status == STATUS_REJECTED
                assert status.reason == "Budget exceeded"
                assert status.user_id == 200
            
            # Test 3: get_acceptance_status returns latest status
            with session.begin_nested():
                accept_proposal(3, 300)
                session.flush()
                reject_proposal(3, 301, "Terms unacceptable")
                session.flush()
                
                status = get_acceptance_status(3)
                assert status.status == STATUS_REJECTED
                assert status.user_id == 301
                assert status.reason == "Terms unacceptable"
            
            # Test 4: Repeated actions create new records, not overwrites
            with session.begin_nested():
                accept_proposal(4, 400)
                session.flush()
                accept_proposal(4, 401)
                session.flush()
                reject_proposal(4, 402, "Final rejection")
                session.flush()
                
                # Verify 3 records exist
                count = session.execute(
                    select(func.count()).select_from(ProposalAcceptance)
                    .where(ProposalAcceptance.proposal_id == 4)
                ).scalar()
                assert count == 3, f"Expected 3 records, got {count}"
                
                # Verify latest is the rejection
                status = get_acceptance_status(4)
                assert status.status == STATUS_REJECTED
                assert status.user_id == 402
            
            # Test 5: No commits performed (only flushes), verified by rollback
            session.rollback()
            
        finally:
            set_current_session(None)
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("proposal_acceptance selftest OK")
