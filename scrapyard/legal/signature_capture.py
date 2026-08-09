"""
signature_capture — Capture and store digital signatures on contracts for e-signature workflows. Provides secure, auditable storage and retrieval of user signatures tied to specific contracts.

### PART-META-JSON
{
  "name": "signature_capture",
  "layer": "legal",
  "purpose": "Capture and store digital signatures on contracts for e-signature workflows. Provides secure, auditable storage and retrieval of user signatures tied to specific contracts.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: capture_signature(contract_id, user_id, signature); get_signature(contract_id, user_id); Signature(...).",
  "outputs": "Returns: capture_signature -> None; get_signature -> bytes | None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.legal.signature_capture`.",
  "example": "from scrapyard.legal.signature_capture import *",
  "import_path": "scrapyard.legal.signature_capture"
}
### END-PART-META
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone

from sqlalchemy import Integer, DateTime, LargeBinary, func, select, create_engine, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

_session_maker = None


class Signature(IntPKModel):
    __tablename__ = "signature"
    
    contract_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    signature_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    
    __table_args__ = (
        UniqueConstraint('contract_id', 'user_id', name='uix_contract_user_signature'),
    )


def _configure_engine(engine):
    global _session_maker
    _session_maker = sessionmaker(bind=engine)


def capture_signature(contract_id: int, user_id: int, signature: bytes) -> None:
    """Capture and store a digital signature, overwriting any existing signature for the contract/user pair."""
    if _session_maker is None:
        raise RuntimeError("Database engine not configured")
    
    with _session_maker.begin() as session:
        stmt = select(Signature).where(
            Signature.contract_id == contract_id,
            Signature.user_id == user_id
        )
        existing = session.execute(stmt).scalar_one_or_none()
        
        if existing:
            existing.signature_bytes = signature
            existing.created_at = datetime.now(timezone.utc)
        else:
            new_sig = Signature(
                contract_id=contract_id,
                user_id=user_id,
                signature_bytes=signature
            )
            session.add(new_sig)


def get_signature(contract_id: int, user_id: int) -> bytes | None:
    """Retrieve a signature by contract and user ID. Returns None if not found."""
    if _session_maker is None:
        raise RuntimeError("Database engine not configured")
    
    with _session_maker() as session:
        stmt = select(Signature.signature_bytes).where(
            Signature.contract_id == contract_id,
            Signature.user_id == user_id
        )
        result = session.execute(stmt).scalar_one_or_none()
        return result


def _selftest():
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_signature.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        _configure_engine(engine)
        
        try:
            # Test capture and retrieve
            test_data = b"test_signature_bytes_12345"
            capture_signature(1, 100, test_data)
            retrieved = get_signature(1, 100)
            assert retrieved == test_data, f"Retrieval mismatch: expected {test_data}, got {retrieved}"
            
            # Test non-existent returns None
            assert get_signature(999, 999) is None, "Should return None for non-existent signature"
            
            # Test overwrite behavior (no error, updates data)
            new_data = b"updated_signature_bytes_67890"
            capture_signature(1, 100, new_data)
            retrieved = get_signature(1, 100)
            assert retrieved == new_data, f"Overwrite failed: expected {new_data}, got {retrieved}"
            
            # Test separate entries for different contracts/users
            capture_signature(2, 200, b"contract2_sig")
            assert get_signature(1, 100) == new_data, "Original signature corrupted"
            assert get_signature(2, 200) == b"contract2_sig", "New signature not stored correctly"
            
            logger.info("signature_capture _selftest passed")
            
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
