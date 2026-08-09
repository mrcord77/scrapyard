"""
tax_calculation - Rule-based tax calculation per country/product type with persisted tax breakdowns.

### PART-META-JSON
{
  "name": "tax_calculation",
  "layer": "billing",
  "purpose": "Rule-based tax calculation per country/product type with persisted tax breakdowns.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure_engine(engine); calculate_taxes(amount, country, product_type).",
  "outputs": "TaxBreakdown rows derived from TaxRule rows (tables 'tax_rule' / 'tax_breakdown').",
  "files_created": [],
  "security_notes": "Money-touching part. Tax rates come from TaxRule rows, not caller input; amounts are validated non-negative. Rates/amounts are Float - acceptable for estimates, but round to 2dp before invoicing and treat the invoice ledger (integer cents) as authoritative. Tax rules are jurisdiction data: keep them updated, wrong rates are a compliance risk not a code risk.",
  "ai_usage": "Import what you need from `scrapyard.billing.tax_calculation`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.billing.tax_calculation import calculate_taxes",
  "import_path": "scrapyard.billing.tax_calculation"
}
### END-PART-META
"""
from __future__ import annotations

from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, JSON, 
    select, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)

# Module-level engine reference (configured at runtime)
_engine = None


def configure_engine(engine) -> None:
    """Configure the SQLAlchemy engine for this module."""
    global _engine
    _engine = engine


class TaxRule(IntPKModel):
    """Tax rules defined per country and product type."""
    __tablename__ = "tax_rule"
    
    country: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    product_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    
    __table_args__ = (
        UniqueConstraint('country', 'product_type', 'name', name='uq_tax_rule_country_product_name'),
    )


class TaxBreakdown(IntPKModel):
    """Records applied tax details per invoice/calculation."""
    __tablename__ = "tax_breakdown"
    
    invoice_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    product_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    tax_amount: Mapped[float] = mapped_column(Float, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    rules_applied: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


def calculate_taxes(amount: float, country: str, product_type: str) -> TaxBreakdown:
    """
    Calculate taxes based on amount, country, and product type.
    
    Args:
        amount: The base amount to tax
        country: ISO country code
        product_type: Category of product
        
    Returns:
        TaxBreakdown: Persisted breakdown of the tax calculation
        
    Raises:
        RuntimeError: If engine not configured
        ValueError: If amount is negative
    """
    if _engine is None:
        raise RuntimeError("Database engine not configured. Call configure_engine() first.")
    
    if amount < 0:
        raise ValueError("Amount cannot be negative")
    
    with Session(_engine) as session:
        stmt = select(TaxRule).where(
            TaxRule.country == country,
            TaxRule.product_type == product_type,
            TaxRule.is_active == True
        )
        rules = session.execute(stmt).scalars().all()
        
        tax_amount = 0.0
        rules_applied: List[Dict[str, Any]] = []
        
        for rule in rules:
            rule_tax = amount * rule.rate
            tax_amount += rule_tax
            rules_applied.append({
                'rule_id': rule.id,
                'name': rule.name,
                'rate': rule.rate,
                'tax_amount': rule_tax
            })
        
        total_amount = amount + tax_amount
        
        breakdown = TaxBreakdown(
            country=country,
            product_type=product_type,
            amount=amount,
            tax_amount=tax_amount,
            total_amount=total_amount,
            rules_applied=rules_applied
        )
        
        session.add(breakdown)
        session.commit()
        session.refresh(breakdown)
        session.expunge(breakdown)
        
        return breakdown


def _selftest() -> None:
    """
    Self-contained unit tests using temporary SQLite.
    Must complete in under 20 seconds.
    """
    import tempfile
    import os
    from sqlalchemy import create_engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "tax_test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            configure_engine(engine)
            IntPKModel.metadata.create_all(engine)
            
            with Session(engine) as session:
                rules = [
                    TaxRule(country="US", product_type="parts", rate=0.08, name="State Tax"),
                    TaxRule(country="US", product_type="parts", rate=0.02, name="Local Tax"),
                    TaxRule(country="CA", product_type="electronics", rate=0.13, name="HST"),
                    TaxRule(country="DE", product_type="standard", rate=0.19, name="MwSt", is_active=False),
                ]
                session.add_all(rules)
                session.commit()
            
            bd1 = calculate_taxes(100.0, "US", "parts")
            assert bd1.amount == 100.0
            assert abs(bd1.tax_amount - 10.0) < 0.001
            assert abs(bd1.total_amount - 110.0) < 0.001
            assert bd1.country == "US"
            assert bd1.product_type == "parts"
            assert len(bd1.rules_applied) == 2
            assert bd1.id is not None
            
            bd2 = calculate_taxes(100.0, "CA", "electronics")
            assert abs(bd2.tax_amount - 13.0) < 0.001
            assert abs(bd2.total_amount - 113.0) < 0.001
            assert len(bd2.rules_applied) == 1
            
            bd3 = calculate_taxes(100.0, "XX", "unknown")
            assert bd3.tax_amount == 0.0
            assert bd3.total_amount == 100.0
            assert bd3.rules_applied == []
            
            bd4 = calculate_taxes(0.0, "US", "parts")
            assert bd4.tax_amount == 0.0
            assert bd4.total_amount == 0.0
            
            with Session(engine) as session:
                retrieved = session.get(TaxBreakdown, bd1.id)
                assert retrieved is not None
                assert abs(retrieved.tax_amount - 10.0) < 0.001
                count = session.execute(select(func.count(TaxBreakdown.id))).scalar()
                assert count == 4
            
            bd5 = calculate_taxes(100.0, "DE", "standard")
            assert bd5.tax_amount == 0.0
            assert len(bd5.rules_applied) == 0
            
            try:
                calculate_taxes(-10.0, "US", "parts")
                assert False, "Should have raised ValueError"
            except ValueError:
                pass
            
            assert isinstance(bd1, TaxBreakdown)
            
        finally:
            engine.dispose()
            configure_engine(None)


if __name__ == "__main__":
    _selftest()
    print("tax_calculation selftest OK")
