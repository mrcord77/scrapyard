"""
ticket_closure — Manages the finalization of support tickets with validation and resolution tracking. Ensures closure is only applied when conditions are met, using predefined templates.

### PART-META-JSON
{
  "name": "ticket_closure",
  "layer": "support",
  "purpose": "Manages the finalization of support tickets with validation and resolution tracking. Ensures closure is only applied when conditions are met, using predefined templates.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure_session(engine); validate_closure(ticket); close_ticket(ticket_id, resolution); ResolutionTemplate(...); TicketClosure(...); Ticket(...).",
  "outputs": "Returns: validate_closure -> bool; close_ticket -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.ticket_closure`.",
  "example": "from scrapyard.support.ticket_closure import *",
  "import_path": "scrapyard.support.ticket_closure"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class ResolutionTemplate(IntPKModel):
    """Approved resolution text templates."""
    __tablename__ = "resolution_template"
    
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    template_text: Mapped[str] = mapped_column(String(500), nullable=False)


class TicketClosure(IntPKModel):
    """Immutable closure records for audit trails."""
    __tablename__ = "ticket_closure"
    
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("ticket.id"), nullable=False)
    resolution: Mapped[str] = mapped_column(String(100), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), 
                                                default=lambda: datetime.now(timezone.utc))
    
    # Enforce one closure per ticket (immutable record)
    __table_args__ = (
        UniqueConstraint('ticket_id', name='uq_ticket_closure_ticket_id'),
    )


class Ticket(IntPKModel):
    """Minimal ticket model for validation and testing."""
    __tablename__ = "ticket"
    
    status: Mapped[str] = mapped_column(String(50), default="open")
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


# Module-level session factory (configured at runtime)
_session_factory: Optional[sessionmaker] = None


def configure_session(engine):
    """Configure the session factory with an engine."""
    global _session_factory
    _session_factory = sessionmaker(bind=engine)


def _get_session() -> Session:
    """Get a new session from the configured factory."""
    if _session_factory is None:
        raise RuntimeError("Session factory not configured. Call configure_session() first.")
    return _session_factory()


def validate_closure(ticket: Ticket) -> bool:
    """
    Validate if a ticket can be closed.
    
    Returns False if:
    - Ticket is None
    - Ticket is already closed (closure record exists)
    """
    if ticket is None:
        return False
    
    if ticket.id is None:
        return False
    
    session = _get_session()
    try:
        # Check if closure record already exists (ticket already closed)
        existing = session.execute(
            select(TicketClosure).where(TicketClosure.ticket_id == ticket.id)
        ).scalar_one_or_none()
        
        if existing is not None:
            return False
        
        return True
    finally:
        session.close()


def close_ticket(ticket_id: int, resolution: str) -> None:
    """
    Close a ticket with the specified resolution template.
    
    Args:
        ticket_id: The ID of the ticket to close
        resolution: The name of the resolution template to use
        
    Raises:
        ValueError: If ticket not found, validation fails, or template not found
    """
    session = _get_session()
    try:
        # Fetch ticket
        ticket = session.get(Ticket, ticket_id)
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id} not found")
        
        # Validate closure conditions
        if not validate_closure(ticket):
            raise ValueError(f"Ticket {ticket_id} cannot be closed (already closed or invalid)")
        
        # Verify resolution template exists
        template = session.execute(
            select(ResolutionTemplate).where(ResolutionTemplate.name == resolution)
        ).scalar_one_or_none()
        
        if template is None:
            raise ValueError(f"Resolution template '{resolution}' not found")
        
        # Create immutable closure record
        closure = TicketClosure(
            ticket_id=ticket_id,
            resolution=resolution
        )
        session.add(closure)
        
        # Update ticket status
        ticket.status = "closed"
        
        session.commit()
        logger.info(f"Ticket {ticket_id} closed with resolution template: {resolution}")
        
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _selftest():
    """
    Selftest function to verify module functionality.
    Runs offline with temporary SQLite database.
    """
    from sqlalchemy import create_engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create all tables
        IntPKModel.metadata.create_all(engine)
        
        # Configure session for this test
        configure_session(engine)
        
        # Test scenario
        session = Session(engine)
        try:
            # Setup: Create resolution templates
            templates = [
                ResolutionTemplate(name="resolved_fixed", template_text="Issue has been resolved."),
                ResolutionTemplate(name="resolved_duplicate", template_text="Duplicate of existing ticket."),
            ]
            for t in templates:
                session.add(t)
            
            # Setup: Create test ticket
            ticket = Ticket(status="open", description="Test ticket")
            session.add(ticket)
            session.commit()
            
            ticket_id = ticket.id
            
            # Test 1: validate_closure returns True for valid ticket
            assert validate_closure(ticket) is True, "Valid open ticket should pass validation"
            
            # Test 2: Resolution templates enforced - invalid template should fail
            try:
                close_ticket(ticket_id, "invalid_template")
                assert False, "Should raise ValueError for invalid resolution template"
            except ValueError as e:
                assert "not found" in str(e)
            
            # Test 3: Successful closure with valid template
            close_ticket(ticket_id, "resolved_fixed")
            
            # Test 4: Closure record persisted correctly
            closure = session.execute(
                select(TicketClosure).where(TicketClosure.ticket_id == ticket_id)
            ).scalar_one()
            
            assert closure is not None, "Closure record should exist in database"
            assert closure.resolution == "resolved_fixed"
            assert closure.closed_at is not None
            assert closure.ticket_id == ticket_id
            
            # Test 5: Ticket status updated and validate_closure returns False
            session.refresh(ticket)
            assert ticket.status == "closed"
            assert validate_closure(ticket) is False, "Already closed ticket should fail validation"
            
            # Test 6: Prevent re-closure
            try:
                close_ticket(ticket_id, "resolved_duplicate")
                assert False, "Should not allow closing already closed ticket"
            except ValueError:
                pass
            
            # Test 7: validate_closure returns False for None
            assert validate_closure(None) is False
            
            # Test 8: Non-existent ticket ID should raise error in close_ticket
            try:
                close_ticket(9999, "resolved_fixed")
                assert False, "Should raise ValueError for non-existent ticket"
            except ValueError:
                pass
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
