"""
ledger_entry — Append-only payments ledger with per-account balances.

### PART-META-JSON
{
  "name": "ledger_entry",
  "layer": "payments_reconci",
  "purpose": "Record immutable ledger entries (charges/payouts) per account and compute account balances by summation.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "set_engine(engine); record_ledger_entry({account_id, amount, entry_type, timestamp, description}); get_balance_for_account(account_id).",
  "outputs": "Frozen LedgerEntry dataclasses (immutable snapshots of persisted rows in table 'ledger_entry'); float balance per account.",
  "files_created": [],
  "security_notes": "Money-touching part. The ledger is append-only by convention (no update/delete API is exposed) and returned LedgerEntry snapshots are frozen dataclasses, so callers cannot mutate history through this API. A UNIQUE (account_id, timestamp) constraint blocks accidental double-posting of the same instant. Honest limits: amounts are Float columns, so balances are float sums - keep amounts to 2 decimal places and use integer-cents parts (billing/invoices, refund_processor) for authoritative guards; negative balances are permitted by design and only logged; record_ledger_entry passes the input dict straight to the ORM constructor, so callers must not forward untrusted key sets (unknown keys raise TypeError, but a malicious 'id' key could collide a primary key).",
  "ai_usage": "Import from `scrapyard.payments_reconci.ledger_entry`; call set_engine() first; treat this as the reporting ledger, not the enforcement point.",
  "example": "from scrapyard.payments_reconci.ledger_entry import record_ledger_entry",
  "import_path": "scrapyard.payments_reconci.ledger_entry"
}
### END-PART-META
"""
from sqlalchemy import String, Float, Text, DateTime, func, select, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel, Base

STATUS = "core"
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional, Dict, Any
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

_engine = None


@dataclass(frozen=True)
class LedgerEntry:
    account_id: str
    amount: float
    entry_type: str  # 'charge' or 'payout'
    timestamp: datetime
    description: Optional[str] = None


class Ledger(IntPKModel):
    __tablename__ = 'ledger_entry'

    account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(10), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint('account_id', 'timestamp', name='uc_account_id_timestamp'),
        Index('idx_account_id_amount', 'account_id', 'amount')
    )


def set_engine(engine):
    """Configure the database engine for the module."""
    global _engine
    _engine = engine


def create_session(bind=None):
    """Create a new database session."""
    effective_bind = bind if bind is not None else _engine
    if effective_bind is None:
        raise RuntimeError("Database engine not configured")
    Session = sessionmaker(bind=effective_bind)
    return Session()


def record_ledger_entry(entry_data: Dict[str, Any]) -> LedgerEntry:
    """Record a new ledger entry and return an immutable LedgerEntry."""
    session = create_session()
    try:
        entry = Ledger(**entry_data)
        session.add(entry)
        session.commit()
        session.refresh(entry)
        
        if entry.amount < 0:
            logger.info(f"Negative amount ledger entry for account {entry.account_id}: {entry.amount}")
            
        return LedgerEntry(
            account_id=entry.account_id,
            amount=entry.amount,
            entry_type=entry.entry_type,
            timestamp=entry.timestamp,
            description=entry.description
        )
    finally:
        session.close()


def get_balance_for_account(account_id: str) -> float:
    """Calculate current balance for account using SQLAlchemy 2.0 style queries."""
    session = create_session()
    try:
        stmt = select(func.sum(Ledger.amount)).where(Ledger.account_id == account_id)
        result = session.execute(stmt).scalar()
        balance = float(result) if result is not None else 0.0
        
        if balance < 0:
            logger.info(f"Negative balance detected for account {account_id}: {balance}")
            
        return balance
    finally:
        session.close()


def _selftest():
    from sqlalchemy import create_engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'ledger_test.db')
        engine = create_engine(f'sqlite:///{db_path}', echo=False)
        
        original_engine = _engine
        set_engine(engine)
        
        try:
            Base.metadata.create_all(engine)
            base_time = datetime.now(timezone.utc)
            
            # Test record_ledger_entry creates entry with correct data
            charge_entry = record_ledger_entry({
                'account_id': '12345',
                'amount': 100.0,
                'entry_type': 'charge',
                'description': 'Charge for service',
                'timestamp': base_time
            })
            assert charge_entry.account_id == '12345'
            assert charge_entry.amount == 100.0
            assert charge_entry.entry_type == 'charge'
            
            # Test immutability of LedgerEntry (frozen dataclass)
            try:
                charge_entry.amount = 200.0
                assert False, "LedgerEntry should be immutable"
            except AttributeError:
                pass
            
            # Test get_balance_for_account with multiple entries
            payout_entry = record_ledger_entry({
                'account_id': '12345',
                'amount': -50.0,
                'entry_type': 'payout',
                'description': 'Payout to customer',
                'timestamp': base_time + timedelta(seconds=1)
            })
            balance = get_balance_for_account('12345')
            assert balance == 50.0, f"Expected 50.0, got {balance}"
            
            # Test negative balances are allowed but logged
            record_ledger_entry({
                'account_id': '12345',
                'amount': -60.0,
                'entry_type': 'payout',
                'description': 'Payout to customer',
                'timestamp': base_time + timedelta(seconds=2)
            })
            negative_balance = get_balance_for_account('12345')
            assert negative_balance == -10.0, f"Expected -10.0, got {negative_balance}"
            
            # Test account isolation
            other_balance = get_balance_for_account('99999')
            assert other_balance == 0.0
            
            logger.info("Self-test passed successfully")
        finally:
            set_engine(original_engine)
            engine.dispose()


if __name__ == "__main__":
    _selftest()
