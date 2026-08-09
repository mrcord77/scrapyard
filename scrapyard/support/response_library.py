"""
response_library — ** The `scrapyard.support.response_library` module provides a reusable, structured way to manage and retrieve pre-defined canned responses for support desk agents, ensuring consistency and efficiency 

### PART-META-JSON
{
  "name": "response_library",
  "layer": "support",
  "purpose": "Provides a reusable, structured way to manage and retrieve pre-defined canned responses for support desk agents, ensuring consistency and efficiency.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: get_canned_responses(session, category); add_canned_response(session, response); ResponseCategory(...); CannedResponse(...).",
  "outputs": "Returns: get_canned_responses -> List[CannedResponse]; add_canned_response -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.response_library`.",
  "example": "from scrapyard.support.response_library import *",
  "import_path": "scrapyard.support.response_library"
}
### END-PART-META
"""
from sqlalchemy import String, Text, JSON, DateTime, ForeignKey, select
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


class ResponseCategory(IntPKModel):
    """Category for organizing canned responses with hierarchical support."""
    __tablename__ = "response_category"
    
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("response_category.id"), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Hierarchical relationships
    children: Mapped[List["ResponseCategory"]] = relationship(
        "ResponseCategory",
        back_populates="parent",
        foreign_keys="ResponseCategory.parent_id"
    )
    parent: Mapped[Optional["ResponseCategory"]] = relationship(
        "ResponseCategory",
        back_populates="children",
        remote_side=lambda: [ResponseCategory.id],
        foreign_keys=[parent_id]
    )
    
    # Relationship to responses
    responses: Mapped[List["CannedResponse"]] = relationship(
        "CannedResponse", 
        back_populates="category",
        cascade="all, delete-orphan"
    )


class CannedResponse(IntPKModel):
    """Stored canned response with metadata."""
    __tablename__ = "canned_response"
    
    category_id: Mapped[int] = mapped_column(ForeignKey("response_category.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    response_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    
    category: Mapped["ResponseCategory"] = relationship("ResponseCategory", back_populates="responses")


def get_canned_responses(session: Session, category: str) -> List[CannedResponse]:
    """Retrieve all canned responses for a given category name.
    
    Args:
        session: SQLAlchemy session for database operations
        category: Name of the category to filter by
        
    Returns:
        List of CannedResponse objects belonging to the category
    """
    stmt = select(CannedResponse).join(ResponseCategory).where(ResponseCategory.name == category)
    return list(session.scalars(stmt).all())


def add_canned_response(session: Session, response: CannedResponse) -> None:
    """Add a new canned response to the database.
    
    Args:
        session: SQLAlchemy session for database operations
        response: CannedResponse instance to persist
    """
    session.add(response)


def _selftest() -> None:
    """Run self-test to verify module functionality."""
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
            # Test: Create categories
            cat_general = ResponseCategory(name="General", description="General support")
            cat_billing = ResponseCategory(name="Billing", parent_id=None)
            session.add(cat_general)
            session.add(cat_billing)
            session.commit()
            
            # Test: Verify categories exist
            assert cat_general.id is not None
            assert cat_billing.id is not None
            
            # Test: Add canned responses
            resp1 = CannedResponse(
                category_id=cat_general.id,
                title="Welcome Message",
                content="Welcome to our support system!",
                response_metadata={"language": "en", "tags": ["greeting"]}
            )
            resp2 = CannedResponse(
                category_id=cat_general.id,
                title="Closing Message",
                content="Thank you for contacting us.",
                response_metadata={"language": "en"}
            )
            resp3 = CannedResponse(
                category_id=cat_billing.id,
                title="Refund Policy",
                content="Refunds are processed within 5 days.",
                response_metadata={}
            )
            
            add_canned_response(session, resp1)
            add_canned_response(session, resp2)
            add_canned_response(session, resp3)
            session.commit()
            
            # Test: Get canned responses for General
            general_responses = get_canned_responses(session, "General")
            assert len(general_responses) == 2
            titles = {r.title for r in general_responses}
            assert "Welcome Message" in titles
            assert "Closing Message" in titles
            
            # Test: Get canned responses for Billing
            billing_responses = get_canned_responses(session, "Billing")
            assert len(billing_responses) == 1
            assert billing_responses[0].title == "Refund Policy"
            
            # Test: Get canned responses for non-existent category
            empty_responses = get_canned_responses(session, "NonExistent")
            assert len(empty_responses) == 0
            
            # Test: Verify ORM relationships
            assert len(cat_general.responses) == 2
            assert cat_general.responses[0].category.name == "General"
            
            logger.info("Selftest passed: All CRUD operations working correctly")
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
