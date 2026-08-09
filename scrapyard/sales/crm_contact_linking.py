"""
crm_contact_linking — Link contacts to leads, accounts, or other contacts based on relationships, enabling CRM pipeline tracking and relationship management.

### PART-META-JSON
{
  "name": "crm_contact_linking",
  "layer": "sales",
  "purpose": "Link contacts to leads, accounts, or other contacts based on relationships, enabling CRM pipeline tracking and relationship management.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure(session_factory); link_contact_to_lead(contact_id, lead_id); get_linked_contacts(entity_id); ContactLink(...).",
  "outputs": "Returns: configure -> None; link_contact_to_lead -> None; get_linked_contacts -> List[int].",
  "files_created": [
    "contact_link"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.sales.crm_contact_linking`.",
  "example": "from scrapyard.sales.crm_contact_linking import *",
  "import_path": "scrapyard.sales.crm_contact_linking"
}
### END-PART-META
"""

from sqlalchemy import Integer, String, select, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from typing import List, Optional, Callable
import logging

logger = logging.getLogger(__name__)

# Module-level session factory configuration
_session_factory: Optional[Callable[[], Session]] = None


class ContactLink(IntPKModel):
    """ORM model linking contacts to entities (leads, accounts, etc.)."""
    __tablename__ = "contact_link"
    
    contact_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, default="lead")
    
    __table_args__ = (
        UniqueConstraint('contact_id', 'entity_id', 'entity_type', name='uq_contact_entity_link'),
        Index('idx_entity_lookup', 'entity_id'),
    )


def configure(session_factory: Optional[Callable[[], Session]]) -> None:
    """Configure the module with a session factory."""
    global _session_factory
    _session_factory = session_factory


def _get_session() -> Session:
    """Get a session from the configured factory."""
    if _session_factory is None:
        raise RuntimeError("Module not configured. Call configure() first.")
    return _session_factory()


def _validate_positive_id(value: int, name: str) -> None:
    """Validate that an ID is a positive integer."""
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value}")


def link_contact_to_lead(contact_id: int, lead_id: int) -> None:
    """
    Link a contact to a lead by creating a record in contact_link.
    
    Args:
        contact_id: The ID of the contact to link
        lead_id: The ID of the lead to link to
        
    Raises:
        ValueError: If IDs are not positive integers
        RuntimeError: If module is not configured with a session factory
    """
    _validate_positive_id(contact_id, "contact_id")
    _validate_positive_id(lead_id, "lead_id")
    
    session = _get_session()
    try:
        link = ContactLink(
            contact_id=contact_id,
            entity_id=lead_id,
            entity_type="lead"
        )
        session.add(link)
        session.commit()
        logger.debug(f"Linked contact {contact_id} to lead {lead_id}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_linked_contacts(entity_id: int) -> List[int]:
    """
    Get all contact IDs linked to a specific entity.
    
    Args:
        entity_id: The ID of the entity (lead, account, etc.) to query
        
    Returns:
        List of contact IDs linked to the entity
        
    Raises:
        ValueError: If entity_id is not a positive integer
        RuntimeError: If module is not configured with a session factory
    """
    _validate_positive_id(entity_id, "entity_id")
    
    session = _get_session()
    try:
        stmt = select(ContactLink.contact_id).where(ContactLink.entity_id == entity_id)
        result = session.execute(stmt).scalars().all()
        return list(result)
    finally:
        session.close()


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    import tempfile
    import os
    from sqlalchemy import create_engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_crm_linking.db")
        engine = create_engine(f"sqlite:///{db_path}", future=True)
        
        # Create tables
        ContactLink.metadata.create_all(engine)
        
        # Configure session factory for testing
        TestSession = sessionmaker(bind=engine)
        configure(TestSession)
        
        try:
            # Test 1: Linking creates a record
            link_contact_to_lead(1, 100)
            contacts = get_linked_contacts(100)
            assert 1 in contacts, "Contact 1 should be linked to entity 100"
            
            # Test 2: Multiple links handled correctly
            link_contact_to_lead(2, 100)
            link_contact_to_lead(3, 200)
            
            contacts_100 = get_linked_contacts(100)
            assert sorted(contacts_100) == [1, 2], f"Expected [1, 2], got {contacts_100}"
            
            contacts_200 = get_linked_contacts(200)
            assert contacts_200 == [3], f"Expected [3], got {contacts_200}"
            
            # Verify no cross-contamination
            assert get_linked_contacts(999) == []
            
            # Test 3: Invalid IDs raise ValueError
            try:
                link_contact_to_lead(0, 100)
                assert False, "Should raise ValueError for contact_id 0"
            except ValueError:
                pass
            
            try:
                link_contact_to_lead(1, -1)
                assert False, "Should raise ValueError for negative lead_id"
            except ValueError:
                pass
            
            try:
                get_linked_contacts(0)
                assert False, "Should raise ValueError for entity_id 0"
            except ValueError:
                pass
            
            # Test 4: Session management (ensure no lingering transactions/sessions)
            # The functions should close sessions properly (verified by no exceptions above)
            # and commits should only happen on success.
            
            # Verify exception handling doesn't leave session in bad state
            initial_count = len(get_linked_contacts(300))
            try:
                # Duplicate link should raise IntegrityError
                link_contact_to_lead(5, 300)
                link_contact_to_lead(5, 300)  # Duplicate
                assert False, "Should have raised exception for duplicate"
            except Exception:
                pass  # Expected
            
            # Session should still work after exception
            final_count = len(get_linked_contacts(300))
            assert final_count == initial_count + 1, "Only one link should exist despite duplicate attempt"
            
        finally:
            # Cleanup
            configure(None)
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("crm_contact_linking selftest OK")
