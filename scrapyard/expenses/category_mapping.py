"""
category_mapping — Map expenses to predefined business categories for consistent financial reporting and analysis. Enables flexible and maintainable categorization of expenses across different business contexts.

### PART-META-JSON
{
  "name": "category_mapping",
  "layer": "expenses",
  "purpose": "Map expenses to predefined business categories for consistent financial reporting and analysis. Enables flexible and maintainable categorization of expenses across different business contexts.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "map_to_category(expense, session); get_category_by_name(name, session). Expense model is owned by this part (table 'category_mapping_expense').",
  "outputs": "Category rows (auto-created 'Standard'/'High Value' buckets) and CategoryMapping join rows; mapping is idempotent per expense.",
  "files_created": [],
  "security_notes": "Categorization rules are code-defined (amount threshold), not user-supplied strings - no expression evaluation. Category names are auto-created from a fixed set; if rules are ever made configurable, whitelist rule fields rather than eval'ing them. No PII stored beyond expense amounts.",
  "ai_usage": "Import what you need from `scrapyard.expenses.category_mapping`.",
  "example": "from scrapyard.expenses.category_mapping import *",
  "import_path": "scrapyard.expenses.category_mapping"
}
### END-PART-META
"""

from __future__ import annotations

from sqlalchemy import String, Integer, Float, ForeignKey, select, create_engine, inspect
from sqlalchemy.orm import Mapped, mapped_column, Session, object_session
from scrapyard.database.base_model import IntPKModel
from typing import Optional
import time
import os
import tempfile
import logging

logger = logging.getLogger(__name__)

class Expense(IntPKModel):
    """Expense model owned by this part (scrapyard.expenses.models does not exist;
    this definition is the real, primary path)."""
    __tablename__ = "category_mapping_expense"

    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class Category(IntPKModel):
    __tablename__ = "category_mapping_category"
    
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class CategoryMapping(IntPKModel):
    __tablename__ = "category_mapping"
    
    expense_id: Mapped[int] = mapped_column(Integer, ForeignKey("category_mapping_expense.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("category_mapping_category.id"), nullable=False)


def get_category_by_name(name: str, session: Optional[Session] = None) -> Optional[Category]:
    """Get a category by its name."""
    if session is None:
        raise ValueError("Session is required to lookup category")
    
    stmt = select(Category).where(Category.name == name)
    return session.execute(stmt).scalar_one_or_none()


def map_to_category(expense: Expense, session: Optional[Session] = None) -> Category:
    """Map an expense to a category based on configurable rules."""
    if session is None:
        session = object_session(expense)
        if session is None:
            raise ValueError("Expense must be attached to a session or session must be provided")
    
    # Check if mapping already exists
    existing = session.execute(
        select(CategoryMapping).where(CategoryMapping.expense_id == expense.id)
    ).scalar_one_or_none()
    
    if existing:
        category = session.get(Category, existing.category_id)
        if category:
            return category
    
    # Configurable rules: High value (>1000) vs Standard
    category_name = "High Value" if (hasattr(expense, 'amount') and expense.amount and expense.amount > 1000) else "Standard"
    
    category = get_category_by_name(category_name, session)
    if category is None:
        category = Category(name=category_name, description=f"Auto-created {category_name}")
        session.add(category)
        session.flush()
    
    # Create mapping
    mapping = CategoryMapping(expense_id=expense.id, category_id=category.id)
    session.add(mapping)
    session.flush()
    
    return category


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create all tables
        IntPKModel.metadata.create_all(engine)
        
        with Session(engine) as session:
            # Setup: Create categories
            cat_std = Category(name="Standard", description="Standard expenses")
            cat_high = Category(name="High Value", description="High value expenses")
            session.add(cat_std)
            session.add(cat_high)
            session.commit()
            
            # Test get_category_by_name
            found = get_category_by_name("Standard", session)
            assert found is not None, "Should find Standard category"
            assert found.name == "Standard"
            assert found.description == "Standard expenses"
            
            not_found = get_category_by_name("NonExistent", session)
            assert not_found is None, "Should return None for non-existent category"
            
            # Create test expense (low amount)
            exp1 = Expense(amount=500)
            session.add(exp1)
            session.commit()
            
            # Test map_to_category creates mapping and returns correct category
            result1 = map_to_category(exp1, session)
            assert result1.name == "Standard", f"Expected Standard, got {result1.name}"
            
            # Verify mapping exists in table
            mapping1 = session.execute(
                select(CategoryMapping).where(CategoryMapping.expense_id == exp1.id)
            ).scalar_one_or_none()
            assert mapping1 is not None, "Mapping should be created"
            assert mapping1.category_id == result1.id
            
            # Test idempotency: calling again returns same category without creating duplicate
            result1_again = map_to_category(exp1, session)
            assert result1_again.id == result1.id
            
            # Create high value expense
            exp2 = Expense(amount=1500)
            session.add(exp2)
            session.commit()

            result2 = map_to_category(exp2, session)
            assert result2.name == "High Value", f"Expected High Value, got {result2.name}"

            # Verify table schemas (tables carry the '<part>_' prefix from the
            # collision rename)
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            assert "category_mapping_category" in tables, "category table must exist"
            assert "category_mapping_expense" in tables, "expense table must exist"
            assert "category_mapping" in tables, "category_mapping table must exist"

            # Verify category schema
            cat_cols = {c['name'] for c in inspector.get_columns('category_mapping_category')}
            assert 'id' in cat_cols and 'name' in cat_cols and 'description' in cat_cols
            
            # Verify category_mapping schema
            map_cols = {c['name'] for c in inspector.get_columns('category_mapping')}
            assert 'id' in map_cols and 'expense_id' in map_cols and 'category_id' in map_cols
        
        engine.dispose()
    
    elapsed = time.time() - start_time
    assert elapsed < 20, f"Self-test took {elapsed:.2f}s, must be under 20s"
    logger.info(f"_selftest passed in {elapsed:.2f}s")


if __name__ == "__main__":
    _selftest()
    print("category_mapping selftest OK")
