"""
credit_allocator — Automatically allocate credits based on breach severity and contract terms, enforcing contract rules and ensuring fair credit distribution across service agreements.

### PART-META-JSON
{
  "name": "credit_allocator",
  "layer": "support",
  "purpose": "Automatically allocate credits based on breach severity and contract terms, enforcing contract rules and ensuring fair credit distribution across service agreements.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "scrapyard.database.base_model",
    "sqlalchemy",
    "datetime"
  ],
  "inputs": "Public API: allocate_credits(breach, rules); Breach(...); AllocationRule(...); CreditAllocation(...).",
  "outputs": "Returns: allocate_credits -> CreditAllocation.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.credit_allocator`.",
  "example": "from scrapyard.support.credit_allocator import *",
  "import_path": "scrapyard.support.credit_allocator"
}
### END-PART-META
"""

from sqlalchemy import Float, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import List
import logging
import tempfile
import os

logger = logging.getLogger(__name__)


class Breach(IntPKModel):
    __tablename__ = 'breaches'
    
    severity: Mapped[float] = mapped_column(Float, nullable=False)
    contract_id: Mapped[int] = mapped_column(Integer, nullable=False)


class AllocationRule(IntPKModel):
    __tablename__ = 'allocation_rules'
    
    severity_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    credit_amount: Mapped[float] = mapped_column(Float, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_id: Mapped[int] = mapped_column(Integer, nullable=False)


class CreditAllocation(IntPKModel):
    __tablename__ = 'credit_allocations'
    
    breach_id: Mapped[int] = mapped_column(ForeignKey('breaches.id'), nullable=False)
    allocated_credits: Mapped[float] = mapped_column(Float, nullable=False)
    rule_id: Mapped[int] = mapped_column(ForeignKey('allocation_rules.id'), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def allocate_credits(breach: Breach, rules: List[AllocationRule]) -> CreditAllocation:
    """
    Allocate credits based on breach severity and contract terms.
    """
    eligible_rules = [
        rule for rule in rules 
        if rule.severity_threshold <= breach.severity and rule.contract_id == breach.contract_id
    ]
    
    if not eligible_rules:
        raise ValueError("No eligible allocation rules found")
    
    # Sort by priority (ascending - lower number is higher priority), 
    # then by credit amount (descending - higher credit first)
    eligible_rules.sort(key=lambda x: (x.priority, -x.credit_amount))
    selected_rule = eligible_rules[0]
    
    allocation = CreditAllocation(
        breach_id=breach.id,
        allocated_credits=selected_rule.credit_amount,
        rule_id=selected_rule.id,
        timestamp=datetime.now(timezone.utc)
    )
    
    return allocation


def _selftest():
    from sqlalchemy import create_engine
    from scrapyard.database.base_model import Base
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, 'test.db')
        engine = create_engine(f'sqlite:///{db_path}', echo=False)
        
        Base.metadata.create_all(engine)
        
        with Session(engine) as session:
            # Create test data
            breach1 = Breach(id=1, severity=2.5, contract_id=101)
            breach2 = Breach(id=2, severity=3.0, contract_id=102)
            rule1 = AllocationRule(id=1, severity_threshold=2.0, credit_amount=100.0, priority=1, contract_id=101)
            rule2 = AllocationRule(id=2, severity_threshold=3.0, credit_amount=200.0, priority=2, contract_id=102)
            
            session.add_all([breach1, breach2, rule1, rule2])
            session.commit()
            
            # Test allocation
            alloc1 = allocate_credits(breach1, [rule1, rule2])
            alloc2 = allocate_credits(breach2, [rule1, rule2])
            
            assert alloc1.rule_id == 1 and alloc1.allocated_credits == 100.0
            assert alloc2.rule_id == 2 and alloc2.allocated_credits == 200.0
            
            # Verify persistence works
            session.add(alloc1)
            session.add(alloc2)
            session.commit()
            
            # Verify retrieval
            saved_alloc = session.query(CreditAllocation).filter_by(breach_id=1).first()
            assert saved_alloc is not None
            assert saved_alloc.rule_id == 1
            assert saved_alloc.allocated_credits == 100.0
            
            # Verify rule retrieval
            saved_rule = session.get(AllocationRule, 1)
            assert saved_rule is not None
            assert saved_rule.credit_amount == 100.0
        
        engine.dispose()


if __name__ == "__main__":
    _selftest()
