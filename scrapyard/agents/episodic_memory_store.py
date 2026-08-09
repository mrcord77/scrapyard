"""
episodic_memory_store — ** The `episodic_memory_store` module provides a durable, timestamped storage system for episodic memories used by agent systems. It enables agents to record and retrieve contextual experiences over t

### PART-META-JSON
{
  "name": "episodic_memory_store",
  "layer": "agents",
  "purpose": "Provides a durable, timestamped storage system for episodic memories used by agent systems. It enables agents to record and retrieve contextual experiences over t.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: add_memory(memory); retrieve_memories(start_time, end_time, agent_id); Memory(...).",
  "outputs": "Returns: add_memory -> None; retrieve_memories -> List[Memory].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.episodic_memory_store`.",
  "example": "from scrapyard.agents.episodic_memory_store import *",
  "import_path": "scrapyard.agents.episodic_memory_store"
}
### END-PART-META
"""
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, JSON, String, Text, create_engine, select, Index
from sqlalchemy.orm import Mapped, mapped_column, Session
from sqlalchemy.engine import Engine

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None


def _configure_engine(database_url: str) -> None:
    """Internal: Configure the database engine and create tables."""
    global _engine
    _engine = create_engine(database_url, echo=False)
    # Create all tables defined on IntPKModel's metadata
    IntPKModel.metadata.create_all(_engine)


@dataclass
class Memory:
    """Public dataclass representing an episodic memory."""
    timestamp: datetime
    agent_id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None


class _MemoryORM(IntPKModel):
    """Internal ORM model mapping to the memories table."""
    __tablename__ = "episodic_memory_store_memories"
    
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        index=True
    )
    agent_id: Mapped[str] = mapped_column(
        String(255), 
        nullable=False, 
        index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Use 'metadata_' as Python attribute name to avoid conflict with SQLAlchemy's reserved 'metadata'
    # Explicitly map to 'metadata' column name in database
    metadata_: Mapped[Dict[str, Any]] = mapped_column(
        "metadata",
        JSON, 
        default=dict
    )
    
    # Composite index for efficient time-range queries per agent
    __table_args__ = (
        Index('ix_memories_agent_time', 'agent_id', 'timestamp'),
    )


def add_memory(memory: Memory) -> None:
    """Persist a memory to the episodic memory store."""
    if _engine is None:
        raise RuntimeError("Database engine not configured")
    
    orm_obj = _MemoryORM(
        timestamp=memory.timestamp,
        agent_id=memory.agent_id,
        content=memory.content,
        metadata_=memory.metadata
    )
    
    with Session(_engine) as session:
        session.add(orm_obj)
        session.commit()
        session.refresh(orm_obj)
        memory.id = orm_obj.id


def retrieve_memories(
    start_time: datetime, 
    end_time: datetime, 
    agent_id: Optional[str] = None
) -> List[Memory]:
    """Retrieve memories within a time range, optionally filtered by agent_id."""
    if _engine is None:
        raise RuntimeError("Database engine not configured")
    
    with Session(_engine) as session:
        stmt = select(_MemoryORM).where(
            _MemoryORM.timestamp >= start_time,
            _MemoryORM.timestamp <= end_time
        )
        
        if agent_id is not None:
            stmt = stmt.where(_MemoryORM.agent_id == agent_id)
        
        stmt = stmt.order_by(_MemoryORM.timestamp)
        
        result = session.execute(stmt)
        orm_objects = result.scalars().all()
        
        return [
            Memory(
                id=obj.id,
                timestamp=obj.timestamp,
                agent_id=obj.agent_id,
                content=obj.content,
                metadata=dict(obj.metadata_) if obj.metadata_ else {}
            )
            for obj in orm_objects
        ]


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "episodic_memory_test.db")
        db_url = f"sqlite:///{db_path}"
        
        try:
            # Configure with temporary database
            _configure_engine(db_url)
            
            now = datetime.now(timezone.utc)
            past = now - timedelta(hours=2)
            recent = now - timedelta(minutes=30)
            future = now + timedelta(hours=1)
            
            # Test data creation
            mem1 = Memory(
                timestamp=past,
                agent_id="agent_alpha",
                content="Observed a red object",
                metadata={"type": "observation", "priority": 1}
            )
            mem2 = Memory(
                timestamp=recent,
                agent_id="agent_alpha",
                content="Picked up the object",
                metadata={"type": "action", "priority": 2}
            )
            mem3 = Memory(
                timestamp=future,
                agent_id="agent_beta",
                content="Predicted outcome",
                metadata={"type": "prediction", "priority": 3}
            )
            
            # Test add_memory persists and assigns ID
            add_memory(mem1)
            assert mem1.id is not None and mem1.id > 0, "Memory should receive ID after add"
            
            add_memory(mem2)
            assert mem2.id is not None and mem2.id > mem1.id, "Subsequent memory should have higher ID"
            
            add_memory(mem3)
            assert mem3.id is not None, "Third memory should have ID"
            
            # Test retrieve_memories returns all in range
            all_memories = retrieve_memories(past - timedelta(hours=1), future + timedelta(hours=1))
            assert len(all_memories) == 3, f"Expected 3 total memories, got {len(all_memories)}"
            
            # Test filtering by agent_id
            alpha_memories = retrieve_memories(
                past - timedelta(hours=1), 
                future + timedelta(hours=1), 
                agent_id="agent_alpha"
            )
            assert len(alpha_memories) == 2, f"Expected 2 memories for agent_alpha, got {len(alpha_memories)}"
            assert all(m.agent_id == "agent_alpha" for m in alpha_memories)
            assert all(m.id is not None for m in alpha_memories)
            
            # Test time range filtering
            window_memories = retrieve_memories(recent - timedelta(minutes=1), recent + timedelta(minutes=1))
            assert len(window_memories) == 1, f"Expected 1 memory in tight window, got {len(window_memories)}"
            assert window_memories[0].content == "Picked up the object"
            assert window_memories[0].metadata["type"] == "action"
            
            # Test empty result for non-matching filters
            empty_agent = retrieve_memories(past, future, agent_id="nonexistent")
            assert empty_agent == [], "Should return empty list for non-existent agent"
            
            empty_time = retrieve_memories(future + timedelta(days=1), future + timedelta(days=2))
            assert empty_time == [], "Should return empty list for future time range"
            
            # Verify type consistency
            assert isinstance(all_memories[0], Memory)
            assert isinstance(all_memories[0].timestamp, datetime)
            assert isinstance(all_memories[0].metadata, dict)
            
        finally:
            # Cleanup: dispose engine to close all connections
            global _engine
            if _engine is not None:
                _engine.dispose()
                _engine = None


if __name__ == "__main__":
    _selftest()
