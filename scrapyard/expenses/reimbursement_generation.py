"""
reimbursement_generation — ** Generate reimbursement requests from approved expenses, ensuring accurate financial reconciliation and auditability. This module provides a reusable, type-safe, and testable interface for expense-t

### PART-META-JSON
{
  "name": "reimbursement_generation",
  "layer": "expenses",
  "purpose": "Generate reimbursement requests from approved expenses, ensuring accurate financial reconciliation and auditability. This module provides a reusable, type-safe, and testable interface for expense-t.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: generate_reimbursement(expense); calculate_total(expenses, currency); Reimbursement(...); ReimbursementItem(...); Expense(...).",
  "outputs": "Returns: generate_reimbursement -> Reimbursement; calculate_total -> float.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.expenses.reimbursement_generation`.",
  "example": "from scrapyard.expenses.reimbursement_generation import *",
  "import_path": "scrapyard.expenses.reimbursement_generation"
}
### END-PART-META
"""
from sqlalchemy import String, Float, Text, DateTime, func, select, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, Session, object_session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from typing import Optional, List
import os
import tempfile

# ORM Models
class Reimbursement(IntPKModel):
    __tablename__ = 'reimbursement'
    __table_args__ = (
        Index('idx_reimbursement_expense_id', 'expense_id'),
        UniqueConstraint('expense_id', name='unq_reimbursement_expense_id'),
    )

    expense_id: Mapped[int] = mapped_column(ForeignKey('reimbursement_generation_expense.id'), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default='Pending')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.current_timestamp()
    )

class ReimbursementItem(IntPKModel):
    __tablename__ = 'reimbursement_item'

    reimbursement_id: Mapped[int] = mapped_column(ForeignKey('reimbursement.id'), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

# Expense model
class Expense(IntPKModel):
    __tablename__ = 'reimbursement_generation_expense'

    amount: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

# Reimbursement generation functions
def generate_reimbursement(expense: Expense) -> Reimbursement:
    """Generate a reimbursement request from an approved expense.
    
    Args:
        expense: The expense to generate reimbursement for. Must be attached to a session.
        
    Returns:
        Reimbursement: The created reimbursement object with linked items.
        
    Raises:
        ValueError: If expense is not an Expense instance or not attached to a session.
    """
    if not isinstance(expense, Expense):
        raise ValueError("Invalid expense type: expected Expense instance")
    
    # Get the session that the expense is attached to
    session = object_session(expense)
    if session is None:
        raise ValueError("Expense must be attached to a database session")
    
    reimbursement = Reimbursement(expense_id=expense.id)
    session.add(reimbursement)
    session.flush()

    item = ReimbursementItem(
        reimbursement_id=reimbursement.id,
        amount=expense.amount,
        description=expense.description,
        currency=expense.currency
    )
    session.add(item)
    session.flush()
    
    return reimbursement

def calculate_total(expenses: List[Expense], currency: Optional[str] = None) -> float:
    """Calculate total amount of expenses.
    
    Args:
        expenses: List of Expense objects to sum.
        currency: Optional currency code to filter by (e.g., 'USD', 'EUR').
        
    Returns:
        float: The total amount.
        
    Raises:
        ValueError: If expenses is not a list or contains non-Expense items.
    """
    if not isinstance(expenses, list):
        raise ValueError("Expenses must be provided as a list")
    
    if not all(isinstance(e, Expense) for e in expenses):
        raise ValueError("All items must be Expense instances")
    
    if currency is not None:
        if not isinstance(currency, str):
            raise ValueError("Currency must be a string")
        return sum(e.amount for e in expenses if e.currency == currency)
    
    return sum(e.amount for e in expenses)

# Self-test function
def _selftest():
    from sqlalchemy import create_engine
    from scrapyard.database.base_model import Base

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        engine = create_engine(f'sqlite:///{db_path}')
        Base.metadata.create_all(engine)

        # Test exception handling for invalid inputs
        try:
            generate_reimbursement("not an expense")
            assert False, "Should have raised ValueError for invalid type"
        except ValueError as e:
            assert "Invalid expense type" in str(e)
        
        # Test detached expense (no session)
        detached_expense = Expense(amount=10.0, description='Test', currency='USD')
        try:
            generate_reimbursement(detached_expense)
            assert False, "Should have raised ValueError for detached expense"
        except ValueError as e:
            assert "session" in str(e).lower()
        
        try:
            calculate_total("not a list")
            assert False, "Should have raised ValueError for non-list"
        except ValueError as e:
            assert "list" in str(e).lower()
        
        try:
            calculate_total([Expense(), "not an expense"])
            assert False, "Should have raised ValueError for invalid list items"
        except ValueError as e:
            assert "Expense instances" in str(e)
        
        # Test data
        expenses = [
            Expense(id=1, amount=100.50, description='Part 1', currency='USD'),
            Expense(id=2, amount=150.75, description='Part 2', currency='EUR'),
            Expense(id=3, amount=50.00, description='Part 3', currency='USD')
        ]

        with Session(engine) as session:
            # Add expenses to session so they are bound
            for expense in expenses:
                session.add(expense)
            session.flush()
            
            # Generate reimbursements
            reimbursements = []
            for expense in expenses:
                reimbursement = generate_reimbursement(expense)
                assert isinstance(reimbursement, Reimbursement)
                assert reimbursement.expense_id == expense.id
                assert reimbursement.status == 'Pending'
                reimbursements.append(reimbursement)
            
            session.flush()
            session.commit()
            
            # Test calculate_total with all expenses
            total_all = calculate_total(expenses)
            assert total_all == 301.25  # 100.50 + 150.75 + 50.00
            
            # Test calculate_total respecting currency (filtering)
            total_usd = calculate_total(expenses, currency='USD')
            assert total_usd == 150.50  # 100.50 + 50.00
            
            total_eur = calculate_total(expenses, currency='EUR')
            assert total_eur == 150.75
            
            # Test empty list
            assert calculate_total([]) == 0.0
            
            # Test invalid currency type
            try:
                calculate_total(expenses, currency=123)
                assert False, "Should have raised ValueError for invalid currency type"
            except ValueError:
                pass

        # Verify persistence - use new session to ensure data was flushed to DB
        with Session(engine) as session:
            # Query reimbursements
            stmt = select(Reimbursement).order_by(Reimbursement.expense_id)
            db_reimbursements = session.execute(stmt).scalars().all()
            assert len(db_reimbursements) == 3
            
            # Check reimbursement items are linked correctly
            for i, reimb in enumerate(db_reimbursements):
                assert reimb.expense_id == expenses[i].id
                
                # Load items
                items_stmt = select(ReimbursementItem).where(ReimbursementItem.reimbursement_id == reimb.id)
                items = session.execute(items_stmt).scalars().all()
                assert len(items) == 1
                item = items[0]
                assert item.amount == expenses[i].amount
                assert item.currency == expenses[i].currency
                assert item.description == expenses[i].description
            
            # Verify unique constraint on expense_id prevents duplicates
            try:
                dup_reimbursement = Reimbursement(expense_id=1)
                session.add(dup_reimbursement)
                session.flush()
                assert False, "Should have raised integrity error for duplicate expense_id"
            except Exception:
                session.rollback()
        
        engine.dispose()

if __name__ == '__main__':
    _selftest()
