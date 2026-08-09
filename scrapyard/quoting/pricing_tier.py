"""
pricing_tier - Quantity-banded pricing tiers with range validation and per-quantity price resolution.

### PART-META-JSON
{
  "name": "pricing_tier",
  "layer": "quoting",
  "purpose": "Quantity-banded pricing tiers with range validation and per-quantity price resolution.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "apply_tier(quantity, tiers); get_tier_for_quantity(quantity, tiers); validate_tier_range(tier).",
  "outputs": "PricingTier rows (table 'pricing_tiers'); resolved unit prices.",
  "files_created": [],
  "security_notes": "Money-adjacent lookup: tier ranges are validated (min<=max) and resolution is code-only - no user expressions. Prices are Float; keep to 2dp and treat downstream integer-cents invoices as authoritative. Overlapping tier ranges are the caller's data-integrity risk - validate catalogs on ingest.",
  "ai_usage": "Import what you need from `scrapyard.quoting.pricing_tier`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.quoting.pricing_tier import apply_tier",
  "import_path": "scrapyard.quoting.pricing_tier"
}
### END-PART-META
"""
from sqlalchemy import select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from typing import Optional, List
import os, logging, tempfile

logger = logging.getLogger(__name__)

class PricingTier(IntPKModel):
    __tablename__ = "pricing_tiers"
    min_quantity: Mapped[int] = mapped_column(nullable=False)
    max_quantity: Mapped[Optional[int]] = mapped_column(nullable=True)
    price_per_unit: Mapped[float] = mapped_column(nullable=False)

def apply_tier(quantity: int, tiers: List[PricingTier]) -> float:
    tier = get_tier_for_quantity(quantity, tiers)
    if tier is None:
        raise ValueError(f"No valid pricing tier found for quantity: {quantity}")
    return tier.price_per_unit

def get_tier_for_quantity(quantity: int, tiers: List[PricingTier]) -> Optional[PricingTier]:
    # Sort by min_quantity descending (higher minimums first),
    # then by whether max_quantity exists (bounded tiers before unbounded)
    sorted_tiers = sorted(
        tiers, 
        key=lambda t: (t.min_quantity, t.max_quantity is not None), 
        reverse=True
    )
    
    for tier in sorted_tiers:
        if quantity >= tier.min_quantity:
            if tier.max_quantity is None or quantity <= tier.max_quantity:
                return tier
    return None

def validate_tier_range(tier: PricingTier) -> None:
    if tier.min_quantity is not None and tier.max_quantity is not None and tier.min_quantity > tier.max_quantity:
        raise ValueError(f"Invalid range for pricing tier {tier.id}: min_quantity ({tier.min_quantity}) cannot be greater than max_quantity ({tier.max_quantity})")

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'pricing_tiers.db')
        
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create tables
        PricingTier.metadata.create_all(engine)
        
        # Insert test data using ORM
        with Session(engine) as session:
            tiers_data = [
                PricingTier(min_quantity=10, max_quantity=None, price_per_unit=5.0),
                PricingTier(min_quantity=20, max_quantity=30, price_per_unit=4.5),
                PricingTier(min_quantity=30, max_quantity=None, price_per_unit=4.0)
            ]
            for tier in tiers_data:
                session.add(tier)
            session.commit()
            
            # Retrieve all tiers
            all_tiers = session.execute(select(PricingTier)).scalars().all()
            
            # Test apply_tier
            # Quantity 15 should match tier 1 (min=10, max=None, price=5.0) because 15 < 20
            assert apply_tier(15, all_tiers) == 5.0, f"Expected 5.0 for qty 15, got {apply_tier(15, all_tiers)}"
            # Quantity 25 should match tier 2 (min=20, max=30, price=4.5)
            assert apply_tier(25, all_tiers) == 4.5, f"Expected 4.5 for qty 25, got {apply_tier(25, all_tiers)}"
            # Quantity 35 should match tier 3 (min=30, max=None, price=4.0)
            assert apply_tier(35, all_tiers) == 4.0, f"Expected 4.0 for qty 35, got {apply_tier(35, all_tiers)}"
            
            # Test get_tier_for_quantity
            tier = get_tier_for_quantity(15, all_tiers)
            assert tier is not None
            assert tier.min_quantity == 10 and tier.price_per_unit == 5.0
            
            tier = get_tier_for_quantity(25, all_tiers)
            assert tier is not None
            assert tier.min_quantity == 20 and tier.max_quantity == 30 and tier.price_per_unit == 4.5
            
            tier = get_tier_for_quantity(35, all_tiers)
            assert tier is not None
            assert tier.min_quantity == 30 and tier.price_per_unit == 4.0
            
            # Test validate_tier_range with invalid range
            try:
                invalid_tier = PricingTier(min_quantity=20, max_quantity=10)
                validate_tier_range(invalid_tier)
                raise AssertionError("validate_tier_range should have raised an error")
            except ValueError as e:
                # tier.id is None for unsaved object
                expected_msg = "Invalid range for pricing tier None: min_quantity (20) cannot be greater than max_quantity (10)"
                assert str(e) == expected_msg, f"Expected '{expected_msg}', got '{str(e)}'"
            
            # Test validate_tier_range with valid range (should not raise)
            valid_tier = PricingTier(min_quantity=10, max_quantity=20)
            validate_tier_range(valid_tier)  # Should not raise
            
            # Test get_tier_for_quantity with no matching tier (below minimum)
            no_tier = get_tier_for_quantity(5, all_tiers)
            assert no_tier is None
            
            # Test apply_tier with no matching tier (should raise ValueError)
            try:
                apply_tier(5, all_tiers)
                raise AssertionError("apply_tier should have raised an error for quantity 5")
            except ValueError as e:
                assert "No valid pricing tier found for quantity: 5" in str(e)
        
        engine.dispose()

if __name__ == "__main__":
    _selftest()
