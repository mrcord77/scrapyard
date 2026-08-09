"""
model_version_router — ** Route incoming ML requests to the correct model version based on metadata, ensuring consistent and versioned inference behavior. This module enables dynamic model versioning and routing, integratin

### PART-META-JSON
{
  "name": "model_version_router",
  "layer": "ml",
  "purpose": "Route incoming ML requests to the correct model version based on metadata, ensuring consistent and versioned inference behavior. This module enables dynamic model versioning and routing, integratin.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure(db_url); init_db(); get_session(); route_to_model_version(metadata); ModelVersion(...).",
  "outputs": "Returns: configure -> None; init_db -> None; get_session -> Session; route_to_model_version -> str.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.ml.model_version_router`.",
  "example": "from scrapyard.ml.model_version_router import *",
  "import_path": "scrapyard.ml.model_version_router"
}
### END-PART-META
"""

import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from sqlalchemy import Boolean, DateTime, JSON, String, UniqueConstraint, create_engine, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# Module-level state for database configuration
_engine: Optional[Any] = None


class ModelVersion(IntPKModel):
    """Database model for storing model versions and routing metadata."""

    __tablename__ = "versions_table"

    model_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    deployment_tag: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    endpoint_url: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    routing_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("model_name", "version", name="uix_model_version"),
    )


def configure(db_url: Optional[str] = None) -> None:
    """Configure the database engine for the router.
    
    Args:
        db_url: SQLAlchemy database URL. Defaults to SQLite file or env var.
    """
    global _engine
    if db_url is None:
        db_url = os.environ.get("MODEL_ROUTER_DB_URL", "sqlite:///model_router.db")
    _engine = create_engine(db_url, echo=False)


def init_db() -> None:
    """Initialize database tables."""
    if _engine is None:
        configure()
    IntPKModel.metadata.create_all(_engine)


def get_session() -> Session:
    """Get a new database session."""
    if _engine is None:
        configure()
    return Session(_engine)


def route_to_model_version(metadata: dict) -> str:
    """Route incoming ML request to the correct model version endpoint.
    
    Args:
        metadata: Dict containing routing keys:
            - model_name (str, required): Name of the model
            - version (str, optional): Specific version identifier
            - deployment_tag (str, optional): Deployment tag (e.g., 'prod', 'staging')
    
    Returns:
        str: The endpoint URL for the batch inference server of the matched model version.
    
    Raises:
        ValueError: If no active model version matches the metadata or if model_name is missing.
    """
    if _engine is None:
        configure()
    
    model_name = metadata.get("model_name")
    if not model_name:
        raise ValueError("metadata must contain 'model_name'")
    
    target_version = metadata.get("version")
    target_tag = metadata.get("deployment_tag")
    
    with get_session() as session:
        stmt = select(ModelVersion).where(
            ModelVersion.model_name == model_name,
            ModelVersion.is_active == True
        )
        
        if target_version:
            stmt = stmt.where(ModelVersion.version == target_version)
        elif target_tag:
            stmt = stmt.where(ModelVersion.deployment_tag == target_tag)
        else:
            # Default to latest created active version
            stmt = stmt.order_by(ModelVersion.created_at.desc())
        
        result = session.execute(stmt.limit(1))
        record = result.scalar_one_or_none()
        
        if record is None:
            raise ValueError(f"No active model version found for metadata: {metadata}")
        
        return record.endpoint_url


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_router.db")
        db_url = f"sqlite:///{db_path}"
        
        # Configure and initialize test database
        configure(db_url)
        init_db()
        
        # Insert test model versions
        with get_session() as session:
            versions = [
                ModelVersion(
                    model_name="fraud_detector",
                    version="1.0.0",
                    deployment_tag="prod",
                    endpoint_url="http://batch-inference:8080/models/fraud/v1",
                    is_active=True,
                    routing_metadata={"team": "risk"}
                ),
                ModelVersion(
                    model_name="fraud_detector",
                    version="2.0.0-beta",
                    deployment_tag="staging",
                    endpoint_url="http://batch-inference:8080/models/fraud/v2",
                    is_active=True,
                    routing_metadata={"team": "risk", "experimental": True}
                ),
                ModelVersion(
                    model_name="recommender",
                    version="3.5.0",
                    deployment_tag=None,
                    endpoint_url="http://batch-inference:8080/models/rec/latest",
                    is_active=True
                ),
                ModelVersion(
                    model_name="fraud_detector",
                    version="0.9.0",
                    deployment_tag="deprecated",
                    endpoint_url="http://batch-inference:8080/models/fraud/v0",
                    is_active=False
                ),
            ]
            session.add_all(versions)
            session.commit()
        
        # Mock batch inference server for integration testing
        class MockBatchServer:
            def __init__(self):
                self.handlers: Dict[str, Callable[[dict], str]] = {}
            
            def register(self, endpoint: str, handler: Callable[[dict], str]) -> None:
                self.handlers[endpoint] = handler
            
            def submit(self, endpoint: str, payload: dict) -> str:
                if endpoint not in self.handlers:
                    raise ValueError(f"No handler for endpoint: {endpoint}")
                return self.handlers[endpoint](payload)
        
        batch_server = MockBatchServer()
        batch_server.register(
            "http://batch-inference:8080/models/fraud/v1",
            lambda p: "job_fraud_v1_123"
        )
        batch_server.register(
            "http://batch-inference:8080/models/fraud/v2",
            lambda p: "job_fraud_v2_456"
        )
        batch_server.register(
            "http://batch-inference:8080/models/rec/latest",
            lambda p: "job_rec_789"
        )
        
        # Test 1: Route by specific version
        meta = {"model_name": "fraud_detector", "version": "1.0.0"}
        endpoint = route_to_model_version(meta)
        assert endpoint == "http://batch-inference:8080/models/fraud/v1"
        job_id = batch_server.submit(endpoint, {"data": "test1"})
        assert job_id == "job_fraud_v1_123"
        
        # Test 2: Route by deployment tag
        meta = {"model_name": "fraud_detector", "deployment_tag": "staging"}
        endpoint = route_to_model_version(meta)
        assert endpoint == "http://batch-inference:8080/models/fraud/v2"
        job_id = batch_server.submit(endpoint, {"data": "test2"})
        assert job_id == "job_fraud_v2_456"
        
        # Test 3: Route by model name only (latest)
        meta = {"model_name": "recommender"}
        endpoint = route_to_model_version(meta)
        assert endpoint == "http://batch-inference:8080/models/rec/latest"
        job_id = batch_server.submit(endpoint, {"data": "test3"})
        assert job_id == "job_rec_789"
        
        # Test 4: Verify inactive version is not returned
        try:
            route_to_model_version({"model_name": "fraud_detector", "deployment_tag": "deprecated"})
            assert False, "Should have raised ValueError for inactive version"
        except ValueError:
            pass
        
        # Test 5: Verify error on missing model_name
        try:
            route_to_model_version({"version": "1.0.0"})
            assert False, "Should have raised ValueError for missing model_name"
        except ValueError:
            pass
        
        # Test 6: Verify error on non-existent model
        try:
            route_to_model_version({"model_name": "nonexistent_model"})
            assert False, "Should have raised ValueError for non-existent model"
        except ValueError:
            pass
        
        # Cleanup engine to release file handles
        if _engine:
            _engine.dispose()
        
        logger.info("_selftest passed successfully")


if __name__ == "__main__":
    _selftest()
