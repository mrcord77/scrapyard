"""
resource_type — Define and manage resource categories and attributes for scheduling systems. Enables consistent classification and querying of resource types across projects.

### PART-META-JSON
{
  "name": "resource_type",
  "layer": "projects",
  "purpose": "Define and manage resource categories and attributes for scheduling systems. Enables consistent classification and querying of resource types across projects.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: get_resource_type(session, id); list_resource_types(session); ResourceType(...).",
  "outputs": "Returns: get_resource_type -> Optional[ResourceType]; list_resource_types -> List[ResourceType].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.resource_type`.",
  "example": "from scrapyard.projects.resource_type import *",
  "import_path": "scrapyard.projects.resource_type"
}
### END-PART-META
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import tempfile
import os

from sqlalchemy import String, Text, DateTime, JSON, func, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from sqlalchemy.ext.mutable import MutableDict
from scrapyard.database.base_model import IntPKModel


class ResourceType(IntPKModel):
    """SQLAlchemy ORM model for resource types with extensible JSON attributes."""
    
    __tablename__ = "resource_types"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attributes: Mapped[Optional[Dict[str, Any]]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )


def get_resource_type(session: Session, id: int) -> Optional[ResourceType]:
    """Retrieve a resource type by its ID."""
    return session.get(ResourceType, id)


def list_resource_types(session: Session) -> List[ResourceType]:
    """Retrieve all resource types."""
    return list(session.scalars(select(ResourceType)))


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        # Create schema
        ResourceType.metadata.create_all(engine)
        
        with Session(engine) as session:
            # Test creation with JSON attributes
            rt = ResourceType(
                name="Heavy Excavator",
                description="Large scale digging equipment",
                attributes={"weight_tons": 45, "fuel": "diesel", "attachments": ["bucket", "breaker"]}
            )
            session.add(rt)
            session.commit()
            
            # Verify auto-generated fields
            assert rt.id is not None
            assert rt.created_at is not None
            assert rt.updated_at is not None
            
            # Test retrieval by ID
            retrieved = get_resource_type(session, rt.id)
            assert retrieved is not None
            assert retrieved.name == "Heavy Excavator"
            assert retrieved.attributes["weight_tons"] == 45
            
            # Test list operation
            all_types = list_resource_types(session)
            assert len(all_types) == 1
            assert all_types[0].id == rt.id
            
            # Test JSON mutation and persistence
            retrieved.attributes["last_serviced"] = "2024-01-15"
            session.commit()
            
            # Verify update persistence
            check = get_resource_type(session, rt.id)
            assert check.attributes["last_serviced"] == "2024-01-15"
            
            # Verify table schema matches model
            columns = set(ResourceType.__table__.columns.keys())
            required = {"id", "name", "description", "attributes", "created_at", "updated_at"}
            assert required.issubset(columns)
        
        engine.dispose()


if __name__ == "__main__":
    _selftest()
