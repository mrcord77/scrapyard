"""
approver - Manage approvers, delegations, and request assignments.

### PART-META-JSON
{
  "name": "approver",
  "layer": "approvals_workfl",
  "purpose": "Manage approvers, delegations, and request assignments.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "assign_approver(session, request_id, approver_id); get_available_approvers(session, request_id).",
  "outputs": "Approver / Delegation / RequestAssignment rows.",
  "files_created": [],
  "security_notes": "Separation-of-duties surface: assignment does not verify that the approver differs from the requester - enforce self-approval bans in the calling workflow (see approvals policy). Delegations are time-bound rows; expired delegations must be filtered by consumers.",
  "ai_usage": "Import what you need from `scrapyard.approvals_workfl.approver`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.approvals_workfl.approver import assign_approver",
  "import_path": "scrapyard.approvals_workfl.approver"
}
### END-PART-META
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Set

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class Approver(IntPKModel):
    """SQLAlchemy model for approvers."""
    __tablename__ = "approvers"
    
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    role_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class Delegation(IntPKModel):
    """SQLAlchemy model for delegation rules."""
    __tablename__ = "delegations"
    
    from_id: Mapped[int] = mapped_column(ForeignKey("approvers.id"), nullable=False, index=True)
    to_id: Mapped[int] = mapped_column(ForeignKey("approvers.id"), nullable=False, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class RequestAssignment(IntPKModel):
    """Tracks assignment of approvers to specific requests."""
    __tablename__ = "request_assignments"
    
    request_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    approver_id: Mapped[int] = mapped_column(ForeignKey("approvers.id"), nullable=False, index=True)


def assign_approver(session: Session, request_id: int, approver_id: int) -> None:
    """Assign an approver to a request."""
    assignment = RequestAssignment(request_id=request_id, approver_id=approver_id)
    session.add(assignment)
    session.commit()


def get_available_approvers(session: Session, request_id: int) -> List[Approver]:
    """
    Get available approvers for a request, including those available via delegation chains.
    
    Respects delegation hierarchies and expiration dates.
    """
    # Get directly assigned approver IDs
    stmt = select(RequestAssignment.approver_id).where(RequestAssignment.request_id == request_id)
    assigned_ids: Set[int] = set(session.scalars(stmt).all())
    
    if not assigned_ids:
        return []
    
    # BFS through delegation graph to find all reachable approvers
    available_ids: Set[int] = set(assigned_ids)
    queue: List[int] = list(assigned_ids)
    now = datetime.now(timezone.utc)
    
    while queue:
        current_id = queue.pop(0)
        
        # Find active delegations from this approver
        del_stmt = select(Delegation).where(
            Delegation.from_id == current_id,
            Delegation.is_active == True,
            (Delegation.expires_at == None) | (Delegation.expires_at > now)
        )
        
        for delegation in session.scalars(del_stmt):
            if delegation.to_id not in available_ids:
                available_ids.add(delegation.to_id)
                queue.append(delegation.to_id)
    
    if not available_ids:
        return []
    
    # Fetch all active approvers by ID
    approvers_stmt = select(Approver).where(
        Approver.id.in_(available_ids),
        Approver.is_active == True
    )
    return list(session.scalars(approvers_stmt).all())


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    import tempfile
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create all tables
        IntPKModel.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        try:
            # Test data setup
            approver1 = Approver(user_id=101, role_id=1, name="Alice", is_active=True)
            approver2 = Approver(user_id=102, role_id=2, name="Bob", is_active=True)
            approver3 = Approver(user_id=103, role_id=1, name="Charlie", is_active=True)
            inactive_approver = Approver(user_id=104, role_id=2, name="Inactive", is_active=False)
            
            session.add_all([approver1, approver2, approver3, inactive_approver])
            session.commit()
            
            request_id = 999
            
            # Test 1: Assign approver and retrieve
            assign_approver(session, request_id, approver1.id)
            available = get_available_approvers(session, request_id)
            assert len(available) == 1
            assert available[0].id == approver1.id
            assert available[0].name == "Alice"
            
            # Test 2: Add delegation (approver1 -> approver2)
            delegation1 = Delegation(
                from_id=approver1.id,
                to_id=approver2.id,
                is_active=True,
                expires_at=None
            )
            session.add(delegation1)
            session.commit()
            
            available = get_available_approvers(session, request_id)
            assert len(available) == 2
            available_names = {a.name for a in available}
            assert "Alice" in available_names
            assert "Bob" in available_names
            
            # Test 3: Delegation chain (approver2 -> approver3)
            delegation2 = Delegation(
                from_id=approver2.id,
                to_id=approver3.id,
                is_active=True,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1)
            )
            session.add(delegation2)
            session.commit()
            
            available = get_available_approvers(session, request_id)
            assert len(available) == 3
            available_names = {a.name for a in available}
            assert "Charlie" in available_names
            
            # Test 4: Expired delegation should not be included
            delegation2.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            session.commit()
            
            available = get_available_approvers(session, request_id)
            assert len(available) == 2
            available_names = {a.name for a in available}
            assert "Charlie" not in available_names
            
            # Test 5: Inactive approver should not be returned even if delegated
            delegation3 = Delegation(
                from_id=approver1.id,
                to_id=inactive_approver.id,
                is_active=True,
                expires_at=None
            )
            session.add(delegation3)
            session.commit()
            
            available = get_available_approvers(session, request_id)
            # Should still be 2 (Alice and Bob), inactive approver excluded
            assert len(available) == 2
            for app in available:
                assert app.is_active is True
            
            logger.info("All _selftest assertions passed.")
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("approver selftest OK")
