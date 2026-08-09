"""
audit_trail — audit trail

### PART-META-JSON
{
  "name": "audit_trail",
  "layer": "legal",
  "purpose": "audit trail",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure(engine); log_action(contract_id, user_id, action); get_audit_trail(contract_id); AuditLog(...).",
  "outputs": "Returns: configure -> None; log_action -> None; get_audit_trail -> List[AuditLog].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.legal.audit_trail`.",
  "example": "from scrapyard.legal.audit_trail import *",
  "import_path": "scrapyard.legal.audit_trail"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, DateTime, func, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from typing import List, Optional
import tempfile
import os

# Module-level engine storage (configured at runtime, no side effects at import)
_engine: Optional[object] = None


class AuditLog(IntPKModel):
    """Audit log entry for contract lifecycle actions."""
    __tablename__ = "audit_trail_audit_log"
    
    contract_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


def configure(engine: object) -> None:
    """Configure the audit trail module with a SQLAlchemy engine."""
    global _engine
    _engine = engine


def log_action(contract_id: int, user_id: int, action: str) -> None:
    """
    Log a user action on a contract.
    
    Args:
        contract_id: The identifier of the contract
        user_id: The identifier of the user performing the action
        action: Description of the action performed
    """
    if _engine is None:
        raise RuntimeError("audit_trail module not configured with an engine")
    
    with Session(_engine) as session:
        entry = AuditLog(contract_id=contract_id, user_id=user_id, action=action)
        session.add(entry)
        session.commit()


def get_audit_trail(contract_id: int) -> List[AuditLog]:
    """
    Retrieve the complete audit history for a specific contract.
    
    Args:
        contract_id: The identifier of the contract to query
        
    Returns:
        List of audit log entries ordered by creation time
    """
    if _engine is None:
        raise RuntimeError("audit_trail module not configured with an engine")
    
    with Session(_engine) as session:
        stmt = (
            select(AuditLog)
            .where(AuditLog.contract_id == contract_id)
            .order_by(AuditLog.created_at)
        )
        return list(session.scalars(stmt).all())


def _selftest() -> None:
    """
    Self-contained unit tests using temporary SQLite database.
    Validates logging, retrieval, schema correctness, and type safety.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "audit_test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        try:
            # Configure module with temporary test engine
            configure(engine)
            
            # Create tables (verifies schema creation)
            IntPKModel.metadata.create_all(engine)
            
            # Test: log_action creates entries with correct types
            log_action(contract_id=1, user_id=101, action="CREATE_CONTRACT")
            log_action(contract_id=1, user_id=101, action="UPDATE_STATUS")
            log_action(contract_id=2, user_id=202, action="CREATE_CONTRACT")
            
            # Test: get_audit_trail returns all logs for a contract_id
            logs_contract_1: List[AuditLog] = get_audit_trail(1)
            assert len(logs_contract_1) == 2, f"Expected 2 logs, got {len(logs_contract_1)}"
            
            # Verify schema: id, contract_id, user_id, action, created_at all present and typed
            first_log = logs_contract_1[0]
            assert isinstance(first_log.id, int), "id should be int"
            assert isinstance(first_log.contract_id, int), "contract_id should be int"
            assert isinstance(first_log.user_id, int), "user_id should be int"
            assert isinstance(first_log.action, str), "action should be str"
            assert isinstance(first_log.created_at, datetime), "created_at should be datetime"
            
            # Verify content correctness
            assert first_log.contract_id == 1
            assert first_log.user_id == 101
            assert first_log.action == "CREATE_CONTRACT"
            
            second_log = logs_contract_1[1]
            assert second_log.action == "UPDATE_STATUS"
            
            # Test: get_audit_trail isolation between contracts
            logs_contract_2 = get_audit_trail(2)
            assert len(logs_contract_2) == 1
            assert logs_contract_2[0].user_id == 202
            
            # Test: empty list for non-existent contract
            logs_empty = get_audit_trail(999)
            assert logs_empty == [], "Should return empty list for non-existent contract"
            
        finally:
            # Ensure all connections are closed
            engine.dispose()
            # Reset engine to None for test isolation
            configure(None)


if __name__ == "__main__":
    _selftest()
