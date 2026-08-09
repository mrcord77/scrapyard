"""
proposal_discount_summary - Aggregate and summarize all discounts applied to a proposal for pricing and reporting.

### PART-META-JSON
{
  "name": "proposal_discount_summary",
  "layer": "quoting",
  "purpose": "Aggregate and summarize all discounts applied to a proposal for pricing and reporting.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure(engine); calculate_total_discounts(proposal_id); get_discount_breakdown(proposal_id); export_summary(proposal_id, format).",
  "outputs": "ProposalDiscountSummary rows (table 'proposal_discount_summaries'); Decimal totals; breakdown dicts; JSON/CSV export strings.",
  "files_created": [],
  "security_notes": "Money-touching aggregation: totals are computed with Decimal to avoid float drift in summaries. Read-only over discount data (no mutation of the underlying discounts). Export strings may embed proposal amounts - treat as commercially sensitive output.",
  "ai_usage": "Import what you need from `scrapyard.quoting.proposal_discount_summary`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.quoting.proposal_discount_summary import calculate_total_discounts",
  "import_path": "scrapyard.quoting.proposal_discount_summary"
}
### END-PART-META
"""
"""
scrapyard.quoting.proposal_discount_summary

Aggregates and summarizes all discounts applied to a proposal, providing a centralized 
view of discount allocations for accurate pricing and reporting.
"""

import csv
import io
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# Module-level database configuration (initialized at runtime, not import time)
_engine = None
_SessionFactory = None


def configure(engine) -> None:
    """Configure the module with a SQLAlchemy engine."""
    global _engine, _SessionFactory
    _engine = engine
    _SessionFactory = sessionmaker(bind=engine)


def get_session() -> Session:
    """Get a new session from the configured factory."""
    if _SessionFactory is None:
        raise RuntimeError("Database not configured. Call configure() first.")
    return _SessionFactory()


class ProposalDiscountSummary(IntPKModel):
    """ORM model for proposal discount entries."""
    
    __tablename__ = "proposal_discount_summaries"
    
    proposal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    discount_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc)
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model instance to dictionary representation."""
        return {
            "id": self.id,
            "proposal_id": self.proposal_id,
            "discount_type": self.discount_type,
            "source": self.source,
            "amount": self.amount,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def calculate_total_discounts(proposal_id: int) -> Decimal:
    """
    Calculate the total of all discounts for a given proposal.
    
    Args:
        proposal_id: The unique identifier of the proposal.
        
    Returns:
        Decimal: The sum of all discount amounts (zero if none found).
    """
    session = get_session()
    try:
        stmt = select(func.sum(ProposalDiscountSummary.amount)).where(
            ProposalDiscountSummary.proposal_id == proposal_id
        )
        result = session.execute(stmt).scalar()
        if result is None:
            return Decimal("0.00")
        return Decimal(str(result)).quantize(Decimal("0.01"))
    finally:
        session.close()


def get_discount_breakdown(proposal_id: int) -> List[Dict[str, Any]]:
    """
    Retrieve a detailed breakdown of all discounts for a proposal.
    
    Args:
        proposal_id: The unique identifier of the proposal.
        
    Returns:
        List[Dict[str, Any]]: List of discount records with type, source, and amount.
    """
    session = get_session()
    try:
        stmt = select(ProposalDiscountSummary).where(
            ProposalDiscountSummary.proposal_id == proposal_id
        )
        results = session.execute(stmt).scalars().all()
        return [record.to_dict() for record in results]
    finally:
        session.close()


def export_summary(proposal_id: int, format: str = "json") -> str:
    """
    Export the discount summary in the specified format.
    
    Args:
        proposal_id: The unique identifier of the proposal.
        format: The output format, either "json" or "csv".
        
    Returns:
        str: The formatted summary string.
        
    Raises:
        ValueError: If an unsupported format is requested.
    """
    breakdown = get_discount_breakdown(proposal_id)
    total = calculate_total_discounts(proposal_id)
    format_lower = format.lower()
    
    if format_lower == "json":
        data = {
            "proposal_id": proposal_id,
            "total_discount": str(total),
            "breakdown": breakdown,
        }
        return json.dumps(data, indent=2)
    
    elif format_lower == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Summary section
        writer.writerow(["proposal_id", "total_discount"])
        writer.writerow([proposal_id, str(total)])
        writer.writerow([])
        
        # Detail section
        writer.writerow(["id", "discount_type", "source", "amount", "description", "created_at"])
        for item in breakdown:
            writer.writerow([
                item["id"],
                item["discount_type"],
                item["source"],
                item["amount"],
                item.get("description", ""),
                item.get("created_at", ""),
            ])
        return output.getvalue()
    
    else:
        raise ValueError(f"Unsupported format: {format}. Use 'json' or 'csv'.")


def _selftest() -> None:
    """
    Module self-test using temporary SQLite database.
    
    Verifies discount aggregation, breakdown accuracy, and export functionality.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            configure(engine)
            IntPKModel.metadata.create_all(engine)
            
            # Populate test data
            session = Session(bind=engine)
            try:
                discounts = [
                    ProposalDiscountSummary(
                        proposal_id=1,
                        discount_type="volume",
                        source="bulk_tier_3",
                        amount=125.50,
                        description="Volume discount",
                    ),
                    ProposalDiscountSummary(
                        proposal_id=1,
                        discount_type="loyalty",
                        source="vip_customer",
                        amount=75.00,
                        description="Loyalty reward",
                    ),
                    ProposalDiscountSummary(
                        proposal_id=1,
                        discount_type="special_offer",
                        source="promo_q4",
                        amount=50.00,
                        description="Seasonal promotion",
                    ),
                    ProposalDiscountSummary(
                        proposal_id=2,
                        discount_type="volume",
                        source="bulk_tier_1",
                        amount=25.00,
                    ),
                ]
                session.add_all(discounts)
                session.commit()
            finally:
                session.close()
            
            # Test aggregation
            total = calculate_total_discounts(1)
            assert isinstance(total, Decimal)
            assert total == Decimal("250.50")
            assert calculate_total_discounts(2) == Decimal("25.00")
            assert calculate_total_discounts(999) == Decimal("0")
            
            # Test breakdown
            breakdown = get_discount_breakdown(1)
            assert len(breakdown) == 3
            assert all(isinstance(d, dict) for d in breakdown)
            types = {d["discount_type"] for d in breakdown}
            assert types == {"volume", "loyalty", "special_offer"}
            
            # Test JSON export
            json_str = export_summary(1, "json")
            json_data = json.loads(json_str)
            assert json_data["proposal_id"] == 1
            assert json_data["total_discount"] == "250.50"
            assert len(json_data["breakdown"]) == 3
            
            # Test CSV export
            csv_str = export_summary(1, "csv")
            assert "250.50" in csv_str
            assert "volume" in csv_str
            assert "loyalty" in csv_str
            assert "special_offer" in csv_str
            
            # Test empty proposal
            empty_breakdown = get_discount_breakdown(999)
            assert empty_breakdown == []
            
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("proposal_discount_summary selftest OK")
