"""
semantic_memory_index — Indexes semantic or vector memories for efficient recall scoring. Enables agents to query and retrieve relevant memories based on vector similarity.

### PART-META-JSON
{
  "name": "semantic_memory_index",
  "layer": "agents",
  "purpose": "Indexes semantic or vector memories for efficient recall scoring. Enables agents to query and retrieve relevant memories based on vector similarity.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure_session_factory(factory); add_vector(vector, metadata); recall_top_n(query_vector, n); VectorModel(...).",
  "outputs": "Returns: configure_session_factory -> None; add_vector -> None; recall_top_n -> List[Dict].",
  "files_created": [
    "vectors"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.semantic_memory_index`.",
  "example": "from scrapyard.agents.semantic_memory_index import *",
  "import_path": "scrapyard.agents.semantic_memory_index"
}
### END-PART-META
"""

import logging
import math
import os
import tempfile
from typing import Optional, List, Dict, Callable

from sqlalchemy import JSON, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

_session_factory: Optional[Callable[[], Session]] = None


class VectorModel(IntPKModel):
    __tablename__ = "semantic_memory_index_vectors"
    vector: Mapped[List[float]] = mapped_column(JSON)
    meta: Mapped[Dict] = mapped_column(JSON)


def configure_session_factory(factory: Callable[[], Session]) -> None:
    """Configure the session factory for database operations."""
    global _session_factory
    _session_factory = factory


def _get_session() -> Session:
    """Get a new session from the configured factory."""
    if _session_factory is None:
        raise RuntimeError("Session factory not configured")
    return _session_factory()


def _validate_vector(vector: List[float]) -> None:
    """Validate vector format."""
    if not isinstance(vector, list):
        raise ValueError("Vector must be a list")
    if not all(isinstance(x, (int, float)) for x in vector):
        raise ValueError("Vector must contain only numbers")
    if len(vector) == 0:
        raise ValueError("Vector cannot be empty")


def _validate_metadata(metadata: Dict) -> None:
    """Validate metadata schema."""
    if not isinstance(metadata, dict):
        raise ValueError("Metadata must be a dictionary")


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if len(a) != len(b):
        raise ValueError(f"Dimension mismatch: {len(a)} vs {len(b)}")
    
    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    
    return dot_product / (norm_a * norm_b)


def add_vector(vector: List[float], metadata: Dict) -> None:
    """Add a vector with metadata to the index."""
    _validate_vector(vector)
    _validate_metadata(metadata)
    
    session = _get_session()
    try:
        vm = VectorModel(vector=list(vector), meta=dict(metadata))
        session.add(vm)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def recall_top_n(query_vector: List[float], n: int) -> List[Dict]:
    """Recall top N most similar vectors."""
    if n <= 0:
        return []
    
    _validate_vector(query_vector)
    
    session = _get_session()
    try:
        stmt = select(VectorModel)
        results = session.execute(stmt).scalars().all()
        
        if not results:
            return []
        
        expected_dim = len(results[0].vector)
        if len(query_vector) != expected_dim:
            raise ValueError(f"Query dimension {len(query_vector)} != index dimension {expected_dim}")
        
        scored = []
        for vm in results:
            try:
                sim = _cosine_similarity(query_vector, vm.vector)
                scored.append((sim, vm))
            except ValueError:
                continue
        
        scored.sort(key=lambda x: x[0], reverse=True)
        top_n = scored[:n]
        
        return [
            {
                "id": vm.id,
                "metadata": vm.meta,
                "similarity": float(sim)
            }
            for sim, vm in top_n
        ]
    finally:
        session.close()


def _selftest():
    """Offline self-test suite."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        IntPKModel.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(bind=engine)
        configure_session_factory(lambda: SessionLocal())
        
        try:
            # Test empty database
            assert recall_top_n([1.0, 0.0, 0.0], 5) == []
            
            # Test invalid metadata
            try:
                add_vector([1.0, 0.0, 0.0], "invalid")
                assert False
            except ValueError:
                pass
            
            # Test invalid vector type
            try:
                add_vector("not_a_list", {})
                assert False
            except ValueError:
                pass
            
            # Test add and exact recall
            add_vector([1.0, 0.0, 0.0], {"name": "x"})
            results = recall_top_n([1.0, 0.0, 0.0], 1)
            assert len(results) == 1
            assert results[0]["metadata"]["name"] == "x"
            assert abs(results[0]["similarity"] - 1.0) < 1e-9
            
            # Test top N sorting
            add_vector([0.0, 1.0, 0.0], {"name": "y"})  # Orthogonal
            add_vector([0.9, 0.1, 0.0], {"name": "near_x"})  # Close to x
            
            results = recall_top_n([1.0, 0.0, 0.0], 3)
            assert len(results) == 3
            assert results[0]["metadata"]["name"] == "x"
            assert results[1]["metadata"]["name"] == "near_x"
            assert results[2]["metadata"]["name"] == "y"
            assert results[0]["similarity"] > results[1]["similarity"] > results[2]["similarity"]
            
            # Test dimension mismatch
            try:
                recall_top_n([1.0, 0.0], 5)
                assert False
            except ValueError:
                pass
            
            # Test N larger than dataset
            results = recall_top_n([1.0, 0.0, 0.0], 100)
            assert len(results) == 3
            
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
