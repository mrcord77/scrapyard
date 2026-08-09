"""
breach_resolver — Handle resolution of SLA breaches, including manual overrides and corrections. Provides structured tracking and validation of breach resolutions within the system.

### PART-META-JSON
{
  "name": "breach_resolver",
  "layer": "support",
  "purpose": "Handle resolution of SLA breaches, including manual overrides and corrections. Provides structured tracking and validation of breach resolutions within the system.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: resolve_breach(breach_id, resolution_type, notes, resolver_id); ResolutionType(...); BreachResolution(...).",
  "outputs": "Returns: resolve_breach -> BreachResolution.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.breach_resolver`.",
  "example": "from scrapyard.support.breach_resolver import *",
  "import_path": "scrapyard.support.breach_resolver"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, DateTime, Text, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class ResolutionType(str, Enum):
    """Enumeration of valid breach resolution types."""
    CORRECTED = "corrected"
    WAIVED = "waived"
    PENDING = "pending"


class BreachResolution(IntPKModel):
    """ORM model for tracking SLA breach resolutions."""
    __tablename__ = "breach_resolutions"
    
    breach_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    resolution_type: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolver_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<BreachResolution(id={self.id}, breach_id={self.breach_id}, "
            f"type={self.resolution_type})>"
        )


def resolve_breach(
    breach_id: int, 
    resolution_type: ResolutionType, 
    notes: str,
    resolver_id: Optional[int] = None
) -> BreachResolution:
    """
    Create a breach resolution record with validation.
    
    Args:
        breach_id: ID of the SLA breach to resolve
        resolution_type: Type of resolution from ResolutionType enum
        notes: Detailed notes about the resolution
        resolver_id: Optional ID of the user/system performing the resolution
        
    Returns:
        BreachResolution instance (not yet persisted)
        
    Raises:
        ValueError: If resolution_type is not a valid ResolutionType enum
        TypeError: If breach_id is not int or notes is not str
    """
    if not isinstance(resolution_type, ResolutionType):
        raise ValueError(
            f"resolution_type must be ResolutionType enum, got {type(resolution_type)}"
        )
    
    if not isinstance(breach_id, int):
        raise TypeError(f"breach_id must be int, got {type(breach_id)}")
        
    if not isinstance(notes, str):
        raise TypeError(f"notes must be str, got {type(notes)}")
    
    resolution = BreachResolution(
        breach_id=breach_id,
        resolution_type=resolution_type.value,
        notes=notes,
        resolved_at=datetime.now(timezone.utc),
        resolver_id=resolver_id
    )
    
    logger.info(
        "Created breach resolution: breach_id=%s, type=%s, resolver=%s",
        breach_id,
        resolution_type.value,
        resolver_id
    )
    
    return resolution


def _selftest() -> None:
    """
    Offline self-test for breach_resolver module.
    
    Validates:
    - BreachResolution record creation
    - ResolutionType enum validation
    - DB schema creation with correct columns
    - Session add/commit/delete operations
    - Querying by breach_id
    - Enum coercion and error handling
    - Type hint enforcement
    - Offline DB lifecycle management
    """
    engine = None
    session = None
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        try:
            db_path = os.path.join(tmpdir, "test_breach.db")
            engine = create_engine(f"sqlite:///{db_path}", echo=False)
            
            # Verify schema creation
            BreachResolution.metadata.create_all(engine)
            
            SessionLocal = sessionmaker(bind=engine)
            session = SessionLocal()
            
            # Test 1: Valid creation and enum handling
            res = resolve_breach(
                breach_id=1001,
                resolution_type=ResolutionType.WAIVED,
                notes="Management override approved",
                resolver_id=42
            )
            assert res.breach_id == 1001
            assert res.resolution_type == "waived"
            assert res.notes == "Management override approved"
            assert res.resolver_id == 42
            assert isinstance(res.resolved_at, datetime)
            
            # Test 2: Session persistence
            session.add(res)
            session.commit()
            assert res.id is not None and isinstance(res.id, int)
            
            # Test 3: Query by breach_id
            stmt = select(BreachResolution).where(BreachResolution.breach_id == 1001)
            found = session.execute(stmt).scalar_one()
            assert found is not None
            assert found.resolution_type == ResolutionType.WAIVED.value
            
            # Test 4: Multiple records query
            res2 = resolve_breach(
                breach_id=1002,
                resolution_type=ResolutionType.CORRECTED,
                notes="Auto-corrected by system",
                resolver_id=None
            )
            session.add(res2)
            session.commit()
            
            stmt = select(BreachResolution).where(BreachResolution.breach_id == 1002)
            results = session.execute(stmt).scalars().all()
            assert len(results) == 1
            assert results[0].resolution_type == "corrected"
            assert results[0].resolver_id is None
            
            # Test 5: Enum validation error
            try:
                resolve_breach(1003, "invalid_type", "notes")  # type: ignore
                assert False, "Expected ValueError for invalid resolution_type"
            except ValueError as e:
                assert "enum" in str(e).lower() or "ResolutionType" in str(e)
            
            # Test 6: Type enforcement
            try:
                resolve_breach("1004", ResolutionType.PENDING, "notes")  # type: ignore
                assert False, "Expected TypeError for string breach_id"
            except TypeError:
                pass
            
            try:
                resolve_breach(1004, ResolutionType.PENDING, 12345)  # type: ignore
                assert False, "Expected TypeError for int notes"
            except TypeError:
                pass
            
            # Test 7: Delete operations
            stmt = select(BreachResolution).where(BreachResolution.breach_id == 1001)
            to_delete = session.execute(stmt).scalar_one()
            session.delete(to_delete)
            session.commit()
            
            stmt = select(BreachResolution).where(BreachResolution.breach_id == 1001)
            deleted_check = session.execute(stmt).scalar_one_or_none()
            assert deleted_check is None
            
            # Test 8: Pending resolution type
            res3 = resolve_breach(
                breach_id=1003,
                resolution_type=ResolutionType.PENDING,
                notes="Awaiting final approval",
                resolver_id=99
            )
            session.add(res3)
            session.commit()
            assert res3.resolution_type == "pending"
            
            # Test 9: Enum string coercion (ResolutionType is a str subclass)
            assert ResolutionType.CORRECTED == "corrected"
            assert isinstance(ResolutionType.WAIVED, str)
            
            logger.info("breach_resolver _selftest completed successfully")
            
        finally:
            if session:
                session.close()
            if engine:
                engine.dispose()


if __name__ == "__main__":
    _selftest()
