"""
catalog_management - Maintain a structured vendor product/services catalog (categories + items) with guarded updates.

### PART-META-JSON
{
  "name": "catalog_management",
  "layer": "procurement_vend",
  "purpose": "Maintain a structured vendor product/services catalog (categories + items) with guarded updates.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "add_to_catalog(session, item); update_catalog_item(session, item_id, **kwargs).",
  "outputs": "CatalogCategory / CatalogItem rows (tables 'catalog_categories' / 'catalog_items').",
  "files_created": [],
  "security_notes": "update_catalog_item applies keyword updates: unknown attributes are rejected rather than silently set, so callers cannot graft arbitrary fields onto rows. Catalog prices feed procurement decisions - validate vendor-supplied prices on ingest; this part stores what it is given.",
  "ai_usage": "Import what you need from `scrapyard.procurement_vend.catalog_management`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.procurement_vend.catalog_management import add_to_catalog",
  "import_path": "scrapyard.procurement_vend.catalog_management"
}
### END-PART-META
"""
"""
scrapyard.procurement_vend.catalog_management

Maintain a shared, structured catalog of products and services from procurement vendors.
"""

from sqlalchemy import String, Float, Boolean, Text, DateTime, JSON, select, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

__part_meta__ = {
    "name": "scrapyard.procurement_vend.catalog_management",
    "layer": "procurement_vend"
}


class CatalogCategory(IntPKModel):
    """Represents a category in the procurement catalog."""
    __tablename__ = "catalog_categories"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("catalog_categories.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(timezone.utc))
    
    # Relationships - remote_side only on the many-to-one (parent) side
    items: Mapped[List["CatalogItem"]] = relationship("CatalogItem", back_populates="category")
    parent: Mapped[Optional["CatalogCategory"]] = relationship(
        "CatalogCategory", 
        remote_side="CatalogCategory.id", 
        back_populates="children"
    )
    children: Mapped[List["CatalogCategory"]] = relationship(
        "CatalogCategory", 
        back_populates="parent"
    )


class CatalogItem(IntPKModel):
    """Represents an item in the procurement catalog."""
    __tablename__ = "catalog_items"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("catalog_categories.id"), nullable=True, index=True)
    vendor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    specifications: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    
    # Relationships
    category: Mapped[Optional["CatalogCategory"]] = relationship("CatalogCategory", back_populates="items")


def add_to_catalog(session: Session, item: CatalogItem) -> None:
    """
    Add a new item to the catalog.
    
    Args:
        session: SQLAlchemy session
        item: CatalogItem instance to add
    """
    session.add(item)
    session.flush()


def update_catalog_item(session: Session, item_id: int, **kwargs) -> None:
    """
    Update an existing catalog item.
    
    Args:
        session: SQLAlchemy session
        item_id: ID of the item to update
        **kwargs: Attributes to update
    
    Raises:
        ValueError: If item not found
        AttributeError: If invalid attribute provided
    """
    stmt = select(CatalogItem).where(CatalogItem.id == item_id)
    item = session.scalars(stmt).first()
    
    if item is None:
        raise ValueError(f"CatalogItem with id {item_id} not found")
    
    valid_attrs = {col.name for col in CatalogItem.__table__.columns}
    
    for key, value in kwargs.items():
        if key not in valid_attrs:
            raise AttributeError(f"CatalogItem has no attribute '{key}'")
        setattr(item, key, value)
    
    session.flush()


def _selftest() -> None:
    """
    Offline self-test using temporary SQLite database.
    Validates:
    - Add and retrieve catalog item
    - Update catalog item attributes
    - Create and link category to items
    - Session-based operations do not commit
    - Type hints and exception safety
    - Offline SQLite functionality
    """
    import tempfile
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    logger.info("Starting _selftest")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_catalog.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        
        SessionFactory = sessionmaker(bind=engine)
        session = SessionFactory()
        
        try:
            # Test 1: Add and retrieve catalog item
            item = CatalogItem(
                name="Test Motor",
                sku="MOTOR-12V-001",
                unit_price=45.50,
                vendor_name="AutoParts Inc",
                specifications={"voltage": "12V", "rpm": 3000}
            )
            
            add_to_catalog(session, item)
            assert item.id is not None, "Item should have ID after flush"
            
            # Retrieve using select()
            stmt = select(CatalogItem).where(CatalogItem.id == item.id)
            retrieved = session.scalars(stmt).first()
            assert retrieved is not None, "Should retrieve item from DB"
            assert retrieved.name == "Test Motor", "Name should match"
            assert retrieved.sku == "MOTOR-12V-001", "SKU should match"
            
            # Test 2: Update catalog item
            update_catalog_item(session, item.id, name="Updated Motor", unit_price=49.99)
            
            stmt = select(CatalogItem).where(CatalogItem.id == item.id)
            updated = session.scalars(stmt).first()
            assert updated.name == "Updated Motor", "Name should be updated"
            assert updated.unit_price == 49.99, "Price should be updated"
            
            # Test 3: Create and link category
            category = CatalogCategory(name="Electrical", description="Electrical components")
            session.add(category)
            session.flush()
            
            assert category.id is not None, "Category should have ID"
            
            # Link item to category
            update_catalog_item(session, item.id, category_id=category.id)
            
            stmt = select(CatalogItem).where(CatalogItem.id == item.id)
            item_with_cat = session.scalars(stmt).first()
            assert item_with_cat.category_id == category.id, "Category should be linked"
            
            # Verify relationship navigation
            stmt = select(CatalogCategory).where(CatalogCategory.id == category.id)
            cat_with_items = session.scalars(stmt).first()
            assert len(cat_with_items.items) == 1, "Category should have one item"
            assert cat_with_items.items[0].name == "Updated Motor", "Item name should match"
            
            # Test 4: Verify session-based operations do not commit
            # Rollback and verify data is gone (proving API functions don't commit)
            session.rollback()
            
            # New session to verify rollback worked
            session2 = SessionFactory()
            stmt = select(CatalogItem).where(CatalogItem.id == item.id)
            rolled_back_item = session2.scalars(stmt).first()
            assert rolled_back_item is None, "Item should not exist after rollback (no commit in API)"
            
            stmt = select(CatalogCategory).where(CatalogCategory.id == category.id)
            rolled_back_cat = session2.scalars(stmt).first()
            assert rolled_back_cat is None, "Category should not exist after rollback"
            session2.close()
            
            # Test 5: Exception safety - invalid attribute
            session3 = SessionFactory()
            item2 = CatalogItem(name="Test")
            add_to_catalog(session3, item2)
            
            try:
                update_catalog_item(session3, item2.id, invalid_attr="value")
                assert False, "Should raise AttributeError for invalid attribute"
            except AttributeError:
                pass  # Expected
            
            # Test 6: Exception safety - item not found
            try:
                update_catalog_item(session3, 99999, name="Test")
                assert False, "Should raise ValueError for missing item"
            except ValueError:
                pass  # Expected
            
            session3.rollback()
            session3.close()
            
            logger.info("_selftest completed successfully")
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("catalog_management selftest OK")
