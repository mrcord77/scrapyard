"""
prediction_cache — Cache model predictions to improve response times for repeated queries. This module provides a reusable, scalable, and type-safe interface for caching and retrieving predictions using a database-backe

### PART-META-JSON
{
  "name": "prediction_cache",
  "layer": "ml",
  "purpose": "Cache model predictions to improve response times for repeated queries. This module provides a reusable, scalable, and type-safe interface for caching and retrieving predictions using a database-backe",
  "addition": true,
  "status": "core",
  "dependencies": [
    "batch_inference_server"
  ],
  "inputs": "Public API: configure_engine(engine_url); cache_prediction(model_version, input_hash, prediction, ttl); get_cached_prediction(model_version, input_hash); PredictionCacheConfig(...); CacheEntry(...).",
  "outputs": "Returns: cache_prediction -> None; get_cached_prediction -> Optional[Any].",
  "files_created": [
    "cache_table"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.ml.prediction_cache`.",
  "example": "from scrapyard.ml.prediction_cache import *",
  "import_path": "scrapyard.ml.prediction_cache"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, JSON, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional, Any
import os
import logging
import tempfile
import time

logger = logging.getLogger(__name__)

# Module-level engine and session factory for lazy initialization
_engine = None
_Session = None

def _ensure_initialized():
    """Lazy initialization of database engine and session factory."""
    global _engine, _Session
    if _engine is None:
        _engine = create_engine("sqlite:///:memory:", echo=False)
        IntPKModel.metadata.create_all(_engine)
    if _Session is None:
        _Session = sessionmaker(bind=_engine)
    return _Session

def configure_engine(engine_url: Optional[str] = None):
    """Configure the database engine explicitly."""
    global _engine, _Session
    if engine_url is None:
        engine_url = "sqlite:///:memory:"
    _engine = create_engine(engine_url, echo=False)
    _Session = sessionmaker(bind=_engine)
    IntPKModel.metadata.create_all(_engine)
    return _engine

@dataclass(frozen=True)
class PredictionCacheConfig:
    ttl: int = 3600
    cache_table_name: str = "cache_table"

class CacheEntry(IntPKModel):
    __tablename__ = "cache_table"
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prediction: Mapped[JSON] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)

def cache_prediction(model_version: str, input_hash: str, prediction: Any, ttl: int = 3600) -> None:
    """Cache a prediction with optional TTL in seconds."""
    SessionFactory = _ensure_initialized()
    session = SessionFactory()
    try:
        now = datetime.now(timezone.utc)
        entry = CacheEntry(
            model_version=model_version,
            input_hash=input_hash,
            prediction=prediction,
            expires_at=now + timedelta(seconds=ttl)
        )
        session.add(entry)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def get_cached_prediction(model_version: str, input_hash: str) -> Optional[Any]:
    """Retrieve a cached prediction if it exists and hasn't expired."""
    SessionFactory = _ensure_initialized()
    session = SessionFactory()
    try:
        now = datetime.now(timezone.utc)
        stmt = select(CacheEntry).where(
            CacheEntry.model_version == model_version,
            CacheEntry.input_hash == input_hash,
            CacheEntry.expires_at > now
        )
        result = session.execute(stmt).scalar_one_or_none()
        return result.prediction if result else None
    finally:
        session.close()

def _selftest():
    """Offline self-test with temporary SQLite database."""
    global _engine, _Session
    
    # Reset state for clean test
    _engine = None
    _Session = None
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_cache.sqlite")
        configure_engine(f"sqlite:///{db_path}")
        
        # Test caching and retrieval
        cache_prediction("1.0", "abc123", {"output": 42})
        prediction = get_cached_prediction("1.0", "abc123")
        assert prediction == {"output": 42}, f"Expected {{'output': 42}}, got {prediction}"
        
        # Test missing entry
        missing = get_cached_prediction("1.0", "nonexistent")
        assert missing is None, f"Expected None for missing entry, got {missing}"
        
        # Test TTL expiration
        cache_prediction("1.0", "expiring", {"data": "old"}, ttl=0)
        time.sleep(0.01)  # Small delay to ensure expiration
        expired = get_cached_prediction("1.0", "expiring")
        assert expired is None, f"Expected None for expired entry, got {expired}"
        
        # Test versioning (same input hash, different model versions)
        cache_prediction("2.0", "abc123", {"output": "new"})
        v1 = get_cached_prediction("1.0", "abc123")
        v2 = get_cached_prediction("2.0", "abc123")
        assert v1 == {"output": 42}, f"Expected v1 to be unchanged, got {v1}"
        assert v2 == {"output": "new"}, f"Expected v2 to be new, got {v2}"
        
        # Test multiple input hashes
        cache_prediction("1.0", "hash1", {"val": 1})
        cache_prediction("1.0", "hash2", {"val": 2})
        assert get_cached_prediction("1.0", "hash1") == {"val": 1}
        assert get_cached_prediction("1.0", "hash2") == {"val": 2}
        
        print("SELFTEST PASSED")

if __name__ == "__main__":
    _selftest()
