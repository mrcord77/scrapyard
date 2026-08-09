"""
embedding_service — Provide a reusable, scalable interface for managing and serving embedding models, enabling efficient inference and storage of embeddings.

### PART-META-JSON
{
  "name": "embedding_service",
  "layer": "ml",
  "purpose": "Provide a reusable, scalable interface for managing and serving embedding models, enabling efficient inference and storage of embeddings.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "batch_inference_server"
  ],
  "inputs": "Public API: start_embedding_server(config); infer_embeddings(texts, model_version); EmbeddingModel(...).",
  "outputs": "Returns: start_embedding_server -> None; infer_embeddings -> List[Dict[str, Any]].",
  "files_created": [
    "embeddings_table"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import what you need from `scrapyard.ml.embedding_service`.",
  "example": "from scrapyard.ml.embedding_service import *",
  "import_path": "scrapyard.ml.embedding_service"
}
### END-PART-META
"""

from sqlalchemy import String, JSON, select, create_engine, func
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from typing import List, Dict, Any, Optional
import os
import logging
import tempfile
import hashlib

logger = logging.getLogger(__name__)

# Module-level state
_engine: Optional[Any] = None
_SessionLocal: Optional[Any] = None
_model_registry: Dict[str, Dict[str, Any]] = {}
_default_embedding_dim: int = 384


class EmbeddingModel(IntPKModel):
    __tablename__ = "embeddings_table"
    
    text: Mapped[str] = mapped_column(String(1024))
    embedding: Mapped[List[float]] = mapped_column(JSON)
    model_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


def start_embedding_server(config: dict) -> None:
    """Start the embedding server with configurable model loading and endpoint routing."""
    global _engine, _SessionLocal, _model_registry, _default_embedding_dim
    
    db_url = config.get("database_url", os.environ.get("EMBEDDING_DB_URL", "sqlite:///embeddings.db"))
    _default_embedding_dim = config.get("embedding_dim", 384)
    
    _engine = create_engine(db_url, echo=False, future=True)
    IntPKModel.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    
    _model_registry = {}
    versions = config.get("model_versions", ["v1"])
    for version in versions:
        dim = config.get("model_dims", {}).get(version, _default_embedding_dim)
        _model_registry[version] = {"version": version, "dim": dim}
    
    logger.info(f"Embedding server started with models: {list(_model_registry.keys())}")


def _generate_local_embedding(text: str, dim: int) -> List[float]:
    """Generate a deterministic LOCAL embedding with real similarity structure:
    delegates to scrapyard.ai.embeddings.embed (token-level hashed TF vector,
    L2-normalized), so texts sharing words are actually close in cosine space —
    unlike the previous whole-text-hash mock, which carried no semantics."""
    from scrapyard.ai.embeddings import embed
    return embed(text, dim=dim)


# Backwards-compatible alias (previous private name)
_generate_mock_embedding = _generate_local_embedding


def infer_embeddings(texts: List[str], model_version: str) -> List[Dict[str, Any]]:
    """
    Perform inference on texts and store embeddings in database.
    
    Args:
        texts: List of input strings to embed
        model_version: Specific model version to use
        
    Returns:
        List of dictionaries containing id, text, embedding, model_version, and created_at
    """
    global _SessionLocal, _model_registry
    
    if _SessionLocal is None:
        raise RuntimeError("Embedding server not started. Call start_embedding_server first.")
    
    if model_version not in _model_registry:
        raise ValueError(f"Model version '{model_version}' not found in registry")
    
    model_info = _model_registry[model_version]
    dim = model_info["dim"]
    
    records = []
    for text in texts:
        truncated = text[:1024]
        embedding_vec = _generate_mock_embedding(truncated, dim)
        record = EmbeddingModel(
            text=truncated,
            embedding=embedding_vec,
            model_version=model_version,
            created_at=datetime.utcnow()
        )
        records.append(record)
    
    session = _SessionLocal()
    try:
        session.add_all(records)
        session.commit()
        
        for record in records:
            session.refresh(record)
        
        results = []
        for record in records:
            results.append({
                "id": record.id,
                "text": record.text,
                "embedding": record.embedding,
                "model_version": record.model_version,
                "created_at": record.created_at
            })
        
        logger.debug(f"Inferred and stored {len(results)} embeddings using {model_version}")
        return results
        
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to store embeddings: {e}")
        raise
    finally:
        session.close()


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    global _engine, _SessionLocal, _model_registry
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_file = os.path.join(tmpdir, "test.db")
        config = {
            "database_url": f"sqlite:///{db_file}",
            "model_versions": ["v1", "v2"],
            "model_dims": {"v1": 128, "v2": 256},
            "embedding_dim": 128
        }
        
        try:
            start_embedding_server(config)
            assert _engine is not None, "Engine not initialized"
            assert _SessionLocal is not None, "SessionLocal not initialized"
            
            test_texts = ["hello world", "scrapyard test", "embedding service"]
            results = infer_embeddings(test_texts, "v1")
            
            assert len(results) == 3, f"Expected 3 results, got {len(results)}"
            for res in results:
                assert isinstance(res, dict), "Result should be dict"
                assert "id" in res and isinstance(res["id"], int), "Missing or invalid id"
                assert "text" in res and isinstance(res["text"], str), "Missing or invalid text"
                assert "embedding" in res and isinstance(res["embedding"], list), "Missing or invalid embedding"
                assert len(res["embedding"]) == 128, f"Expected dim 128, got {len(res['embedding'])}"
                assert all(isinstance(x, float) for x in res["embedding"]), "Embedding values must be floats"
                assert "model_version" in res and res["model_version"] == "v1", "Version mismatch"
            
            session = _SessionLocal()
            try:
                stmt = select(func.count()).select_from(EmbeddingModel)
                count = session.execute(stmt).scalar()
                assert count == 3, f"Expected 3 rows in DB, found {count}"
                
                stmt = select(EmbeddingModel).where(EmbeddingModel.text == "hello world")
                record = session.execute(stmt).scalar_one()
                assert record.model_version == "v1"
                assert len(record.embedding) == 128
            finally:
                session.close()
            
            v2_results = infer_embeddings(["version test"], "v2")
            assert v2_results[0]["model_version"] == "v2"
            assert len(v2_results[0]["embedding"]) == 256
            
            session = _SessionLocal()
            try:
                stmt = select(func.count()).select_from(EmbeddingModel).where(EmbeddingModel.model_version == "v2")
                v2_count = session.execute(stmt).scalar()
                assert v2_count == 1, f"Expected 1 v2 record, got {v2_count}"
            finally:
                session.close()
            
            try:
                infer_embeddings(["fail"], "invalid_version")
                assert False, "Should raise ValueError for invalid version"
            except ValueError as e:
                assert "invalid_version" in str(e)
            
            logger.info("_selftest completed successfully")
            
        finally:
            if _engine:
                _engine.dispose()
            _engine = None
            _SessionLocal = None
            _model_registry = {}


if __name__ == "__main__":
    _selftest()
