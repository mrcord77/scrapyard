"""
ticket_search — ** The `scrapyard.support.ticket_search` module enables efficient querying and indexing of support tickets, enhancing searchability and auditability within a support desk system. It provides a reusabl

### PART-META-JSON
{
  "name": "ticket_search",
  "layer": "support",
  "purpose": "Enables efficient querying and indexing of support tickets, enhancing searchability and auditability within a support desk system. It provides a reusabl.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure_engine(engine); search_tickets(query); index_ticket(ticket); Ticket(...); TicketIndex(...); SearchQueryLog(...).",
  "outputs": "Returns: search_tickets -> List[Ticket]; index_ticket -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.ticket_search`.",
  "example": "from scrapyard.support.ticket_search import *",
  "import_path": "scrapyard.support.ticket_search"
}
### END-PART-META
"""
from sqlalchemy import String, Text, DateTime, Integer, select, or_, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import List
import logging
import tempfile

logger = logging.getLogger(__name__)

# Module-level engine storage for session management
_engine = None

def configure_engine(engine):
    """Configure the database engine for this module."""
    global _engine
    _engine = engine

@dataclass
class Ticket:
    id: int
    subject: str
    description: str
    created_at: datetime
    updated_at: datetime
    status: str

class TicketIndex(IntPKModel):
    __tablename__ = 'ticket_index'
    
    ticket_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)

class SearchQueryLog(IntPKModel):
    __tablename__ = 'search_query_log'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    query_text: Mapped[str] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(DateTime)

def search_tickets(query: str) -> List[Ticket]:
    """Search tickets by query string in subject or description.
    
    Logs the query to SearchQueryLog for audit purposes.
    """
    if _engine is None:
        raise RuntimeError("Engine not configured. Call configure_engine() first.")
    
    tickets = []
    with Session(_engine) as session:
        # Log the search query with timestamp
        log_entry = SearchQueryLog(
            query_text=query,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(log_entry)
        session.commit()
        
        # Perform full-text search on subject and description
        stmt = select(TicketIndex).where(
            or_(
                TicketIndex.subject.contains(query),
                TicketIndex.description.contains(query)
            )
        )
        
        for idx in session.execute(stmt).scalars():
            ticket = Ticket(
                id=idx.ticket_id,
                subject=idx.subject,
                description=idx.description,
                created_at=idx.created_at,
                updated_at=idx.updated_at,
                status=idx.status
            )
            tickets.append(ticket)
            
    return tickets

def index_ticket(ticket: Ticket) -> None:
    """Index a ticket for search.
    
    If the ticket already exists in the index, it will be updated.
    """
    if _engine is None:
        raise RuntimeError("Engine not configured. Call configure_engine() first.")
    
    with Session(_engine) as session:
        # Check if ticket already exists in index
        existing = session.execute(
            select(TicketIndex).where(TicketIndex.ticket_id == ticket.id)
        ).scalar_one_or_none()
        
        if existing:
            existing.subject = ticket.subject
            existing.description = ticket.description
            existing.created_at = ticket.created_at
            existing.updated_at = ticket.updated_at
            existing.status = ticket.status
        else:
            ticket_index = TicketIndex(
                ticket_id=ticket.id,
                subject=ticket.subject,
                description=ticket.description,
                created_at=ticket.created_at,
                updated_at=ticket.updated_at,
                status=ticket.status
            )
            session.add(ticket_index)
            
        session.commit()

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        conn_str = f'sqlite:///{temp_dir}/test.db'
        engine = create_engine(conn_str)
        
        # Configure the module to use this temporary engine
        configure_engine(engine)
        
        # Create tables in the temporary database
        TicketIndex.metadata.create_all(engine)
        SearchQueryLog.metadata.create_all(engine)
        
        # Sample tickets to index
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        
        sample_tickets = [
            Ticket(id=1, subject="Disk Error", description="The disk on server A is not responding.", created_at=now, updated_at=now, status="Open"),
            Ticket(id=2, subject="Network Down", description="All network connections are down in the office.", created_at=yesterday, updated_at=yesterday, status="Closed")
        ]
        
        # Index sample tickets
        for ticket in sample_tickets:
            index_ticket(ticket)
            
        # Search for "disk" and verify results (also logs the query)
        results = search_tickets("disk")
        assert len(results) == 1, f"Expected 1 result, got {len(results)}"
        assert results[0].subject == "Disk Error", f"Expected 'Disk Error', got '{results[0].subject}'"
        
        # Search for "network" to log another query
        search_tickets("network")
        
        # Verify the log entries were created by search_tickets
        with Session(engine) as session:
            logs = session.execute(select(SearchQueryLog)).scalars().all()
            assert len(logs) == 2, f"Expected 2 log entries (disk, network), got {len(logs)}"
            
            # Verify both queries are logged with correct text
            query_texts = [log.query_text for log in logs]
            assert "disk" in query_texts, "Expected 'disk' in query logs"
            assert "network" in query_texts, "Expected 'network' in query logs"
            
            # Verify timestamps are set
            for log in logs:
                assert log.timestamp is not None, "Expected timestamp to be set"
                assert isinstance(log.timestamp, datetime), "Expected datetime object"
        
        # Dispose the engine to ensure all connections are closed
        engine.dispose()
        
        print("Selftest passed successfully!")

if __name__ == "__main__":
    _selftest()
