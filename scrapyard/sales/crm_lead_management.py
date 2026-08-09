"""
crm_lead_management — Manage the creation, tracking, and updating of leads within the CRM pipeline. Provides a structured way to handle lead lifecycle events and maintain historical status changes.

### PART-META-JSON
{
  "name": "crm_lead_management",
  "layer": "sales",
  "purpose": "Manage the creation, tracking, and updating of leads within the CRM pipeline. Provides a structured way to handle lead lifecycle events and maintain historical status changes.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_lead(session, lead_data); update_lead_status(session, lead_id, status); LeadCreate(...); Lead(...); LeadStatusHistory(...).",
  "outputs": "Returns: create_lead -> Lead; update_lead_status -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.sales.crm_lead_management`.",
  "example": "from scrapyard.sales.crm_lead_management import *",
  "import_path": "scrapyard.sales.crm_lead_management"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, func, select, ForeignKey, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
import tempfile
import os
import logging

logger = logging.getLogger(__name__)


@dataclass
class LeadCreate:
    """Data class for creating a new lead."""
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    status: str = "new"


class Lead(IntPKModel):
    """ORM model for the lead table."""
    __tablename__ = "crm_lead_management_lead"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="new", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


class LeadStatusHistory(IntPKModel):
    """ORM model for tracking lead status history."""
    __tablename__ = "lead_status_history"
    
    lead_id: Mapped[int] = mapped_column(ForeignKey("crm_lead_management_lead.id"), nullable=False, index=True)
    old_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    new_status: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


def create_lead(session: Session, lead_data: LeadCreate) -> Lead:
    """Create a new lead in the database.
    
    Args:
        session: SQLAlchemy session
        lead_data: LeadCreate dataclass containing lead information
        
    Returns:
        The created Lead ORM object
    """
    lead = Lead(
        name=lead_data.name,
        email=lead_data.email,
        phone=lead_data.phone,
        company=lead_data.company,
        status=lead_data.status
    )
    session.add(lead)
    session.flush()
    return lead


def update_lead_status(session: Session, lead_id: int, status: str) -> None:
    """Update lead status and record the change in history.
    
    Args:
        session: SQLAlchemy session
        lead_id: ID of the lead to update
        status: New status value
        
    Raises:
        NoResultFound: If lead_id does not exist
    """
    stmt = select(Lead).where(Lead.id == lead_id)
    lead = session.execute(stmt).scalar_one()
    
    old_status = lead.status
    
    if old_status != status:
        lead.status = status
        lead.updated_at = func.now()
        
        history = LeadStatusHistory(
            lead_id=lead_id,
            old_status=old_status,
            new_status=status
        )
        session.add(history)


def _selftest() -> None:
    """Run offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        try:
            IntPKModel.metadata.create_all(engine)
            SessionLocal = sessionmaker(bind=engine)
            session = SessionLocal()
            
            try:
                lead_data = LeadCreate(
                    name="Test User",
                    email="test@example.com",
                    phone="555-1234",
                    status="new"
                )
                lead = create_lead(session, lead_data)
                assert lead.id is not None
                assert lead.name == "Test User"
                assert lead.status == "new"
                
                update_lead_status(session, lead.id, "qualified")
                session.commit()
                
                session.refresh(lead)
                assert lead.status == "qualified"
                
                history_stmt = select(LeadStatusHistory).where(LeadStatusHistory.lead_id == lead.id)
                records = list(session.execute(history_stmt).scalars().all())
                assert len(records) == 1
                assert records[0].old_status == "new"
                assert records[0].new_status == "qualified"
                
            finally:
                session.close()
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("crm_lead_management selftest OK")
