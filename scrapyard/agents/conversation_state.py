"""
conversation_state — Manages and persists conversation state across interactions, enabling memory-based agents to maintain context and recall past exchanges efficiently.

### PART-META-JSON
{
  "name": "conversation_state",
  "layer": "agents",
  "purpose": "Manages and persists conversation state across interactions, enabling memory-based agents to maintain context and recall past exchanges efficiently.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: setup_database(engine_url); get_session(); save_conversation(conversation_id, content); load_conversation(conversation_id); add_memory(memory_id, content, timestamp); Conversation(...); Memory(...); Vector(...) (plus more).",
  "outputs": "Returns: setup_database -> None; get_session -> Session; save_conversation -> None; load_conversation -> Optional[dict]; add_memory -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.conversation_state`.",
  "example": "from scrapyard.agents.conversation_state import *",
  "import_path": "scrapyard.agents.conversation_state"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, JSON, select, create_engine, Engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker, declarative_base
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import math
import os
import tempfile
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()
_engine: Optional[Engine] = None
_Session: Optional[sessionmaker] = None


class Conversation(Base):
    __tablename__ = "conversations"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    content: Mapped[Dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Memory(Base):
    __tablename__ = "conversation_state_memories"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    content: Mapped[Dict[str, Any]] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)


class Vector(Base):
    __tablename__ = "conversation_state_vectors"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    embedding: Mapped[List[float]] = mapped_column(JSON)


def setup_database(engine_url: str) -> None:
    global _engine, _Session
    _engine = create_engine(engine_url)
    _Session = sessionmaker(bind=_engine)
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    if _Session is None:
        raise RuntimeError("Database not initialized. Call setup_database() first.")
    return _Session()


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def save_conversation(conversation_id: str, content: dict) -> None:
    session = get_session()
    try:
        conv = session.get(Conversation, conversation_id)
        if conv:
            conv.content = content
            conv.updated_at = datetime.utcnow()
        else:
            conv = Conversation(id=conversation_id, content=content)
            session.add(conv)
        session.commit()
    finally:
        session.close()


def load_conversation(conversation_id: str) -> Optional[dict]:
    session = get_session()
    try:
        conv = session.get(Conversation, conversation_id)
        if conv is None:
            return None
        return dict(conv.content)
    finally:
        session.close()


def add_memory(memory_id: str, content: dict, timestamp: datetime) -> None:
    session = get_session()
    try:
        mem = Memory(id=memory_id, content=content, timestamp=timestamp)
        session.merge(mem)
        session.commit()
    finally:
        session.close()


def retrieve_memories(start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[dict]:
    session = get_session()
    try:
        stmt = select(Memory)
        if start is not None:
            stmt = stmt.where(Memory.timestamp >= start)
        if end is not None:
            stmt = stmt.where(Memory.timestamp <= end)
        stmt = stmt.order_by(Memory.timestamp)
        results = session.scalars(stmt).all()
        return [{"id": r.id, "content": r.content, "timestamp": r.timestamp} for r in results]
    finally:
        session.close()


def add_vector(vector_id: str, embedding: List[float]) -> None:
    session = get_session()
    try:
        vec = Vector(id=vector_id, embedding=embedding)
        session.merge(vec)
        session.commit()
    finally:
        session.close()


def score_memory(vector_id: str, query: List[float]) -> float:
    session = get_session()
    try:
        vec = session.get(Vector, vector_id)
        if vec is None:
            return 0.0
        return _cosine_similarity(vec.embedding, query)
    finally:
        session.close()


def rank_memories(query: List[float]) -> List[Tuple[float, str]]:
    session = get_session()
    try:
        vectors = session.scalars(select(Vector)).all()
        results = [(_cosine_similarity(v.embedding, query), v.id) for v in vectors]
        results.sort(reverse=True, key=lambda x: x[0])
        return results
    finally:
        session.close()


def recall_top_n(query: List[float], n: int) -> List[Tuple[float, str]]:
    ranked = rank_memories(query)
    return ranked[:n]


def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        setup_database(f"sqlite:///{db_path}")
        
        # Test save and load conversation
        save_conversation("conv1", {"messages": ["hello"], "turn": 1})
        result = load_conversation("conv1")
        assert result == {"messages": ["hello"], "turn": 1}
        
        save_conversation("conv1", {"messages": ["hello", "world"], "turn": 2})
        result = load_conversation("conv1")
        assert result == {"messages": ["hello", "world"], "turn": 2}
        
        assert load_conversation("nonexistent") is None
        
        # Test episodic memory
        now = datetime.utcnow()
        add_memory("mem1", {"event": "login"}, now)
        add_memory("mem2", {"event": "logout"}, now + timedelta(seconds=1))
        
        memories = retrieve_memories()
        assert len(memories) == 2
        assert memories[0]["id"] == "mem1"
        
        memories = retrieve_memories(start=now + timedelta(seconds=2))
        assert len(memories) == 0
        
        memories = retrieve_memories(end=now + timedelta(seconds=0))
        assert len(memories) == 1
        assert memories[0]["id"] == "mem1"
        
        # Test vectors and semantic recall
        add_vector("v1", [1.0, 0.0, 0.0])
        add_vector("v2", [0.0, 1.0, 0.0])
        add_vector("v3", [0.5, 0.5, 0.0])
        
        score = score_memory("v1", [1.0, 0.0, 0.0])
        assert abs(score - 1.0) < 0.001
        
        score = score_memory("v2", [1.0, 0.0, 0.0])
        assert abs(score - 0.0) < 0.001
        
        ranked = rank_memories([1.0, 0.0, 0.0])
        assert len(ranked) == 3
        assert ranked[0][1] == "v1"
        assert ranked[0][0] > 0.99
        
        top2 = recall_top_n([0.0, 1.0, 0.0], 2)
        assert len(top2) == 2
        assert top2[0][1] == "v2"
        
        # Cleanup
        if _engine:
            _engine.dispose()
        
        logger.info("conversation_state self-test passed")


if __name__ == "__main__":
    _selftest()
