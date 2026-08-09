"""
rate_card_manager — ** Maintains and applies rate cards for labor types and locations, enabling accurate cost estimation and pricing in software products. This module provides a reusable, database-backed system for manag

### PART-META-JSON
{
  "name": "rate_card_manager",
  "layer": "sales",
  "purpose": "Maintains and applies rate cards for labor types and locations, enabling accurate cost estimation and pricing in software products. This module provides a reusable, database-backed system for manag.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: get_rate_for_labor_type(session, labor_type, location); apply_rate_card(session, labor_type, location, hours); update_rate_card(session, labor_type, location, new_rate); RateCard(...); RateCardEntry(...).",
  "outputs": "Returns: get_rate_for_labor_type -> Decimal; apply_rate_card -> Decimal; update_rate_card -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.sales.rate_card_manager`.",
  "example": "from scrapyard.sales.rate_card_manager import *",
  "import_path": "scrapyard.sales.rate_card_manager"
}
### END-PART-META
"""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from sqlalchemy import String, DateTime, ForeignKey, Index, Numeric, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship, sessionmaker

from scrapyard.database.base_model import IntPKModel

import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class RateCard(IntPKModel):
    """Stores rate card metadata (labor_type, location, effective_from, effective_to)."""
    __tablename__ = "rate_card"
    
    labor_type: Mapped[str] = mapped_column(String(100), nullable=False)
    location: Mapped[str] = mapped_column(String(100), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    entries: Mapped[List["RateCardEntry"]] = relationship(
        back_populates="rate_card",
        cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        Index('idx_rate_card_lookup', 'labor_type', 'location'),
    )


class RateCardEntry(IntPKModel):
    """Stores individual rate entries (rate, currency, unit)."""
    __tablename__ = "rate_card_entry"
    
    rate_card_id: Mapped[int] = mapped_column(ForeignKey("rate_card.id"), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="hour")
    
    rate_card: Mapped["RateCard"] = relationship(back_populates="entries")


def _get_active_rate_card(session: Session, labor_type: str, location: str) -> Optional[RateCard]:
    """Helper to retrieve the currently effective rate card."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(RateCard)
        .where(RateCard.labor_type == labor_type)
        .where(RateCard.location == location)
        .where(RateCard.effective_from <= now)
        .where((RateCard.effective_to.is_(None)) | (RateCard.effective_to > now))
        .order_by(RateCard.effective_from.desc())
    )
    return session.execute(stmt).scalars().first()


def get_rate_for_labor_type(session: Session, labor_type: str, location: str) -> Decimal:
    """
    Retrieve the current rate for a given labor type and location.
    
    Raises:
        ValueError: If no active rate card is found.
    """
    rate_card = _get_active_rate_card(session, labor_type, location)
    if rate_card is None or not rate_card.entries:
        raise ValueError(f"No active rate card found for {labor_type} at {location}")
    return rate_card.entries[0].rate


def apply_rate_card(session: Session, labor_type: str, location: str, hours: float) -> Decimal:
    """
    Apply the rate card to calculate total cost for given hours.
    """
    rate = get_rate_for_labor_type(session, labor_type, location)
    return rate * Decimal(str(hours))


def update_rate_card(session: Session, labor_type: str, location: str, new_rate: Decimal) -> None:
    """
    Update the rate for a labor type and location.
    If no active rate card exists, creates a new one effective immediately.
    """
    rate_card = _get_active_rate_card(session, labor_type, location)
    
    if rate_card is None:
        now = datetime.now(timezone.utc)
        rate_card = RateCard(
            labor_type=labor_type,
            location=location,
            effective_from=now
        )
        session.add(rate_card)
        session.flush()
        
        entry = RateCardEntry(
            rate_card_id=rate_card.id,
            rate=new_rate
        )
        session.add(entry)
    else:
        if rate_card.entries:
            rate_card.entries[0].rate = new_rate
        else:
            entry = RateCardEntry(
                rate_card_id=rate_card.id,
                rate=new_rate
            )
            session.add(entry)


def _selftest():
    """Offline self-test suite using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_rate_cards.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        IntPKModel.metadata.create_all(engine)
        
        SessionFactory = sessionmaker(bind=engine)
        session = SessionFactory()
        
        try:
            labor_type = "mechanic"
            location = "detroit"
            initial_rate = Decimal("75.50")
            
            # Create initial rate card
            now = datetime.now(timezone.utc)
            rc = RateCard(
                labor_type=labor_type,
                location=location,
                effective_from=now - timedelta(days=1)
            )
            session.add(rc)
            session.flush()
            
            entry = RateCardEntry(rate_card_id=rc.id, rate=initial_rate)
            session.add(entry)
            session.commit()
            
            # Test retrieval
            retrieved_rate = get_rate_for_labor_type(session, labor_type, location)
            assert retrieved_rate == initial_rate, f"Expected {initial_rate}, got {retrieved_rate}"
            
            # Test apply_rate_card
            hours = 2.5
            total_cost = apply_rate_card(session, labor_type, location, hours)
            expected_cost = initial_rate * Decimal("2.5")
            assert total_cost == expected_cost, f"Expected {expected_cost}, got {total_cost}"
            
            # Test transactional behavior (no commit yet)
            new_rate = Decimal("80.00")
            update_rate_card(session, labor_type, location, new_rate)
            
            # Verify uncommitted state in new session
            session2 = SessionFactory()
            uncommitted_rate = get_rate_for_labor_type(session2, labor_type, location)
            assert uncommitted_rate == initial_rate, "Rate should not update before commit"
            session2.close()
            
            # Commit and verify persistence
            session.commit()
            
            session3 = SessionFactory()
            committed_rate = get_rate_for_labor_type(session3, labor_type, location)
            assert committed_rate == new_rate, f"Expected {new_rate}, got {committed_rate}"
            session3.close()
            
            # Test create via update
            update_rate_card(session, "welder", "chicago", Decimal("95.00"))
            session.commit()
            
            session4 = SessionFactory()
            welder_rate = get_rate_for_labor_type(session4, "welder", "chicago")
            assert welder_rate == Decimal("95.00")
            session4.close()
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
