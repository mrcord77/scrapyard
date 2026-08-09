"""
clause_usage — ** Track which legal clauses are used in which contracts, enabling audit, compliance, and analytics in contract management systems. This module provides a lightweight, reusable way to log and query cl

### PART-META-JSON
{
  "name": "clause_usage",
  "layer": "legal",
  "purpose": "Track which legal clauses are used in which contracts, enabling audit, compliance, and analytics in contract management systems. This module provides a lightweight, reusable way to log and query cl.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: log_clause_usage(contract_id, clause_id); get_clause_usage(clause_id); ClauseUsage(...).",
  "outputs": "Returns: log_clause_usage -> None; get_clause_usage -> list[int].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.legal.clause_usage`.",
  "example": "from scrapyard.legal.clause_usage import *",
  "import_path": "scrapyard.legal.clause_usage"
}
### END-PART-META
"""

import logging
import os
import tempfile
from typing import Callable, Optional

from sqlalchemy import Integer, create_engine, inspect, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# Module-level state for lazy database configuration
_engine: Optional[object] = None
_session_factory: Optional[Callable[[], Session]] = None


def _configure(engine_url: str) -> None:
    """Internal function to configure the database engine."""
    global _engine, _session_factory
    _engine = create_engine(engine_url, echo=False)
    _session_factory = sessionmaker(bind=_engine)


class ClauseUsage(IntPKModel):
    """ORM model tracking usage of legal clauses in contracts."""
    __tablename__ = "clause_usage"
    
    contract_id: Mapped[int] = mapped_column(Integer, nullable=False)
    clause_id: Mapped[int] = mapped_column(Integer, nullable=False)


def log_clause_usage(contract_id: int, clause_id: int) -> None:
    """
    Log that a specific clause is used in a specific contract.
    
    Args:
        contract_id: The identifier of the contract
        clause_id: The identifier of the legal clause
    """
    if _session_factory is None:
        raise RuntimeError("Database not configured")
    
    with _session_factory() as session:
        usage = ClauseUsage(contract_id=contract_id, clause_id=clause_id)
        session.add(usage)
        session.commit()


def get_clause_usage(clause_id: int) -> list[int]:
    """
    Retrieve all contract IDs that use a specific clause.
    
    Args:
        clause_id: The identifier of the legal clause
        
    Returns:
        List of contract IDs using the clause
    """
    if _session_factory is None:
        raise RuntimeError("Database not configured")
    
    with _session_factory() as session:
        stmt = select(ClauseUsage.contract_id).where(ClauseUsage.clause_id == clause_id)
        results = session.scalars(stmt).all()
        return list(results)


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    global _engine, _session_factory
    
    # Save original state
    original_engine = _engine
    original_factory = _session_factory
    
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = os.path.join(tmpdir, "clause_usage_test.db")
            _configure(f"sqlite:///{db_path}")
            
            assert _engine is not None, "Engine not created"
            assert _session_factory is not None, "Session factory not created"
            
            # Create tables
            IntPKModel.metadata.create_all(_engine)
            
            # Verify table schema
            inspector = inspect(_engine)
            tables = inspector.get_table_names()
            assert "clause_usage" in tables, f"Table not found in {tables}"
            
            columns = {col["name"] for col in inspector.get_columns("clause_usage")}
            assert "id" in columns, "Missing id column"
            assert "contract_id" in columns, "Missing contract_id column"
            assert "clause_id" in columns, "Missing clause_id column"
            
            # Test logging and return value
            result = log_clause_usage(1, 100)
            assert result is None, "log_clause_usage should return None"
            
            log_clause_usage(2, 100)
            log_clause_usage(3, 100)
            log_clause_usage(1, 200)
            
            # Test retrieval
            contracts_100 = get_clause_usage(100)
            assert isinstance(contracts_100, list), "Should return list"
            assert sorted(contracts_100) == [1, 2, 3], f"Unexpected result: {contracts_100}"
            
            contracts_200 = get_clause_usage(200)
            assert contracts_200 == [1], f"Expected [1], got {contracts_200}"
            
            contracts_empty = get_clause_usage(999)
            assert contracts_empty == [], f"Expected empty list, got {contracts_empty}"
            
    finally:
        # Cleanup connections and restore state
        if _engine is not None:
            _engine.dispose()
        _engine = original_engine
        _session_factory = original_factory


if __name__ == "__main__":
    _selftest()
