"""
contract_version — Track and manage multiple versions of electronic contracts, ensuring auditability and version control for legal and compliance use. This module provides a structured, reusable way to handle contract version history.

### PART-META-JSON
{
  "name": "contract_version",
  "layer": "legal",
  "purpose": "Tracks and manages multiple versions of electronic contracts for auditability and version control. CANONICAL OWNER of the legal-layer ContractVersion model (table contract_version_contract_version): contract_template imports it instead of defining a duplicate.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model"],
  "inputs": "contract_id integers and immutable content strings; an engine bound via _configure(engine).",
  "outputs": "Version ids, version dicts (id, contract_id, content, created_at), timestamp-ordered version lists.",
  "files_created": [],
  "security_notes": "No authorization checks: any caller can create or read versions for any contract_id, so enforce contract access control in the calling layer. Version rows are append-only by API convention but not enforced at the database level (no UPDATE trigger/guard) - direct DB writers can still mutate history.",
  "ai_usage": "Import what you need from `scrapyard.legal.contract_version`.",
  "example": "from scrapyard.legal.contract_version import *",
  "import_path": "scrapyard.legal.contract_version"
}
### END-PART-META
"""

import logging
from datetime import datetime
from typing import Dict, List, Any

from sqlalchemy import Integer, Text, DateTime, func, select, create_engine, inspect
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# Module metadata for scrapyard system
PART_META = {
    "name": "contract_version",
    "layer": "legal"
}

# Module-level database configuration
_engine = None
_Session = None


class ContractVersion(IntPKModel):
    """ORM model for contract versions with immutable content and timestamps."""
    __tablename__ = "contract_version_contract_version"
    
    contract_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


def _configure(engine):
    """Configure the module with a database engine (internal use)."""
    global _engine, _Session
    _engine = engine
    _Session = sessionmaker(bind=engine)


def create_version(contract_id: int, content: str) -> int:
    """Create a new contract version.
    
    Args:
        contract_id: The contract identifier
        content: The contract content (immutable)
        
    Returns:
        The ID of the newly created version
    """
    if _Session is None:
        raise RuntimeError("Database not configured")
    
    with _Session() as session:
        version = ContractVersion(contract_id=contract_id, content=content)
        session.add(version)
        session.commit()
        return version.id


def get_version_by_id(id: int) -> Dict[str, Any]:
    """Retrieve a specific version by its ID.
    
    Args:
        id: The version ID
        
    Returns:
        Dictionary with version data (id, contract_id, content, created_at), 
        or empty dict if not found
    """
    if _Session is None:
        raise RuntimeError("Database not configured")
    
    with _Session() as session:
        version = session.get(ContractVersion, id)
        if version is None:
            return {}
        return {
            "id": version.id,
            "contract_id": version.contract_id,
            "content": version.content,
            "created_at": version.created_at
        }


def list_versions(contract_id: int) -> List[Dict[str, Any]]:
    """List all versions for a contract, ordered by timestamp ascending (oldest first).
    
    Args:
        contract_id: The contract identifier
        
    Returns:
        List of dictionaries containing version data
    """
    if _Session is None:
        raise RuntimeError("Database not configured")
    
    with _Session() as session:
        stmt = (
            select(ContractVersion)
            .where(ContractVersion.contract_id == contract_id)
            .order_by(ContractVersion.created_at.asc())
        )
        results = session.execute(stmt).scalars().all()
        return [
            {
                "id": v.id,
                "contract_id": v.contract_id,
                "content": v.content,
                "created_at": v.created_at
            }
            for v in results
        ]


def _selftest():
    """Run self-tests using temporary SQLite database."""
    import tempfile
    import os
    import time
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        
        # Configure module for testing
        _configure(engine)
        
        try:
            # Test: Create version and verify stored
            v1_id = create_version(contract_id=1, content="First version content")
            assert isinstance(v1_id, int), "create_version must return int"
            assert v1_id > 0, "Version ID must be positive"
            
            # Test: Retrieve by ID and confirm content matches
            v1_data = get_version_by_id(v1_id)
            assert isinstance(v1_data, dict), "get_version_by_id must return dict"
            assert v1_data["id"] == v1_id
            assert v1_data["contract_id"] == 1
            assert v1_data["content"] == "First version content"
            assert isinstance(v1_data["created_at"], datetime)
            
            # Test: List versions ordered by timestamp
            time.sleep(0.01)  # Ensure distinct timestamps
            v2_id = create_version(contract_id=1, content="Second version")
            time.sleep(0.01)
            v3_id = create_version(contract_id=1, content="Third version")
            
            versions = list_versions(contract_id=1)
            assert isinstance(versions, list), "list_versions must return list"
            assert len(versions) == 3
            assert versions[0]["content"] == "First version content"
            assert versions[1]["content"] == "Second version"
            assert versions[2]["content"] == "Third version"
            
            # Test: Duplicate content creates new version, does not overwrite
            v_dup_id = create_version(contract_id=1, content="First version content")
            versions_with_dup = list_versions(1)
            assert len(versions_with_dup) == 4, "Duplicate content must create new version, not overwrite"
            
            # Verify both versions with same content exist
            contents = [v["content"] for v in versions_with_dup]
            assert contents.count("First version content") == 2
            
            # Test: Different contracts isolated
            other_id = create_version(contract_id=2, content="Other contract")
            contract1_versions = list_versions(1)
            contract2_versions = list_versions(2)
            assert len(contract1_versions) == 4
            assert len(contract2_versions) == 1
            assert contract2_versions[0]["content"] == "Other contract"
            
            # Test: Non-existent returns empty
            assert get_version_by_id(99999) == {}
            assert list_versions(99999) == []
            
            # Test: Type hints validated at runtime
            assert isinstance(create_version(99, "type check"), int)
            assert isinstance(get_version_by_id(v1_id), dict)
            assert isinstance(list_versions(1), list)
            
            # Test: Validate table schema structure
            inspector = inspect(engine)
            columns = {col["name"] for col in inspector.get_columns("contract_version_contract_version")}
            expected_columns = {"id", "contract_id", "content", "created_at"}
            assert columns == expected_columns, f"Schema mismatch: {columns}"
            
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
