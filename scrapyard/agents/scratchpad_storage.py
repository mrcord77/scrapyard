"""
scratchpad_storage — Provides a persistent scratchpad for temporary data storage and manipulation, enabling agents to work with ephemeral data across sessions.

### PART-META-JSON
{
  "name": "scratchpad_storage",
  "layer": "agents",
  "purpose": "Provides a persistent scratchpad for temporary data storage and manipulation, enabling agents to work with ephemeral data across sessions.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_scratchpad(session); store_data(session, scratchpad_id, key, value); retrieve_data(session, scratchpad_id, key); Scratchpad(...); ScratchpadEntry(...).",
  "outputs": "Returns: create_scratchpad -> Scratchpad; store_data -> None; retrieve_data -> Optional[Any].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.scratchpad_storage`.",
  "example": "from scrapyard.agents.scratchpad_storage import *",
  "import_path": "scrapyard.agents.scratchpad_storage"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, JSON, ForeignKey, select, UniqueConstraint, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, Any, List
import os
import tempfile
import inspect
import logging

logger = logging.getLogger(__name__)


class Scratchpad(IntPKModel):
    """Persistent scratchpad for temporary data storage."""
    __tablename__ = "scratchpads"
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        default=None
    )
    
    entries: Mapped[List["ScratchpadEntry"]] = relationship(
        back_populates="scratchpad",
        cascade="all, delete-orphan"
    )


class ScratchpadEntry(IntPKModel):
    """Key-value storage entry associated with a scratchpad."""
    __tablename__ = "scratchpad_entries"
    
    scratchpad_id: Mapped[int] = mapped_column(
        ForeignKey("scratchpads.id"),
        nullable=False
    )
    key: Mapped[str] = mapped_column(
        String,
        nullable=False
    )
    value: Mapped[Any] = mapped_column(
        JSON,
        nullable=True
    )
    
    scratchpad: Mapped[Scratchpad] = relationship(back_populates="entries")
    
    __table_args__ = (
        UniqueConstraint("scratchpad_id", "key", name="uix_scratchpad_key"),
    )


def create_scratchpad(session: Session) -> Scratchpad:
    """Create a new persistent scratchpad with a unique identifier.
    
    Args:
        session: SQLAlchemy session for database operations.
        
    Returns:
        The newly created Scratchpad instance with unique ID.
    """
    scratchpad = Scratchpad()
    session.add(scratchpad)
    session.commit()
    return scratchpad


def store_data(session: Session, scratchpad_id: int, key: str, value: Any) -> None:
    """Store data under a specific key in a scratchpad.
    
    Args:
        session: SQLAlchemy session for database operations.
        scratchpad_id: ID of the target scratchpad.
        key: String key for data retrieval.
        value: JSON-serializable value to store.
        
    Raises:
        ValueError: If scratchpad does not exist or has been deleted.
    """
    scratchpad = session.get(Scratchpad, scratchpad_id)
    if scratchpad is None:
        raise ValueError(f"Scratchpad {scratchpad_id} not found")
    if scratchpad.deleted_at is not None:
        raise ValueError(f"Scratchpad {scratchpad_id} has been deleted")
    
    stmt = select(ScratchpadEntry).where(
        ScratchpadEntry.scratchpad_id == scratchpad_id,
        ScratchpadEntry.key == key
    )
    existing = session.execute(stmt).scalar_one_or_none()
    
    if existing is not None:
        existing.value = value
    else:
        entry = ScratchpadEntry(
            scratchpad_id=scratchpad_id,
            key=key,
            value=value
        )
        session.add(entry)
    
    session.commit()


def retrieve_data(session: Session, scratchpad_id: int, key: str) -> Optional[Any]:
    """Retrieve data stored under a specific key.
    
    Args:
        session: SQLAlchemy session for database operations.
        scratchpad_id: ID of the scratchpad to query.
        key: String key identifying the data.
        
    Returns:
        The stored value if found and scratchpad is active, otherwise None.
    """
    scratchpad = session.get(Scratchpad, scratchpad_id)
    if scratchpad is None or scratchpad.deleted_at is not None:
        return None
    
    stmt = select(ScratchpadEntry).where(
        ScratchpadEntry.scratchpad_id == scratchpad_id,
        ScratchpadEntry.key == key
    )
    entry = session.execute(stmt).scalar_one_or_none()
    
    return entry.value if entry is not None else None


def _selftest() -> None:
    """Offline self-test verifying all functionality with temporary SQLite."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        IntPKModel.metadata.create_all(engine)
        SessionFactory = sessionmaker(bind=engine)
        session = SessionFactory()
        
        try:
            # Test unique ID generation
            pad1 = create_scratchpad(session)
            pad2 = create_scratchpad(session)
            assert pad1.id is not None and pad2.id is not None
            assert pad1.id != pad2.id
            assert isinstance(pad1.id, int)
            assert pad1.deleted_at is None
            
            # Test data storage and retrieval
            test_data = {"list": [1, 2, 3], "str": "test", "num": 42.5}
            store_data(session, pad1.id, "data_key", test_data)
            assert retrieve_data(session, pad1.id, "data_key") == test_data
            
            # Test update existing key
            store_data(session, pad1.id, "data_key", "updated")
            assert retrieve_data(session, pad1.id, "data_key") == "updated"
            
            # Test missing key returns None
            assert retrieve_data(session, pad1.id, "missing") is None
            
            # Test data isolation between scratchpads
            store_data(session, pad2.id, "isolated", "value")
            assert retrieve_data(session, pad1.id, "isolated") is None
            
            # Test deletion prevents retrieval
            pad1.deleted_at = datetime.now(timezone.utc)
            session.commit()
            assert retrieve_data(session, pad1.id, "data_key") is None
            
            # Test storing to deleted pad raises error
            try:
                store_data(session, pad1.id, "new", "value")
                assert False, "Should raise for deleted scratchpad"
            except ValueError:
                pass
            
            # Verify type hints exist
            sig_create = inspect.signature(create_scratchpad)
            assert sig_create.return_annotation == Scratchpad
            assert sig_create.parameters["session"].annotation == Session
            
            sig_store = inspect.signature(store_data)
            assert sig_store.parameters["scratchpad_id"].annotation == int
            assert sig_store.parameters["key"].annotation == str
            assert sig_store.parameters["value"].annotation == Any
            
            sig_retrieve = inspect.signature(retrieve_data)
            assert sig_retrieve.return_annotation == Optional[Any]
            
            import typing
            assert "created_at" in typing.get_type_hints(Scratchpad)
            assert "deleted_at" in typing.get_type_hints(Scratchpad)
            assert "key" in typing.get_type_hints(ScratchpadEntry)
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
