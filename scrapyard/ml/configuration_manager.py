"""
configuration_manager — ** The `scrapyard.ml.configuration_manager` module provides a centralized, type-safe, and versioned mechanism for managing configuration settings used in ML inference serving systems. It ensures consi

### PART-META-JSON
{
  "name": "configuration_manager",
  "layer": "ml",
  "purpose": "Provides a centralized, type-safe, and versioned mechanism for managing configuration settings used in ML inference serving systems. It ensures consi.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: load_config(config_id); save_config(config_id, config_data); ConfigEntry(...).",
  "outputs": "Returns: load_config -> Dict[str, Any]; save_config -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.ml.configuration_manager`.",
  "example": "from scrapyard.ml.configuration_manager import *",
  "import_path": "scrapyard.ml.configuration_manager"
}
### END-PART-META
"""
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import create_engine, DateTime, Integer, JSON, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# PART-META-JSON: {"name": "scrapyard.ml.configuration_manager", "layer": "ml"}

_engine: Optional[Any] = None


class ConfigEntry(IntPKModel):
    __tablename__ = "config_table"
    
    config_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    config_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )
    
    __table_args__ = (
        UniqueConstraint('config_id', 'version', name='uix_config_id_version'),
    )


def _get_engine() -> Any:
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        db_url = os.environ.get("SCRAPYARD_ML_CONFIG_DB_URL")
        if not db_url:
            raise RuntimeError(
                "Database not configured. Set SCRAPYARD_ML_CONFIG_DB_URL environment variable "
                "or use _set_engine() for testing."
            )
        _engine = create_engine(db_url)
        IntPKModel.metadata.create_all(_engine)
    return _engine


def _set_engine(engine: Any) -> None:
    """Set the database engine (primarily for testing)."""
    global _engine
    _engine = engine
    IntPKModel.metadata.create_all(_engine)


def load_config(config_id: str) -> Dict[str, Any]:
    """
    Load the latest configuration for the given config_id.
    
    Args:
        config_id: Unique identifier for the configuration
        
    Returns:
        Dictionary containing the configuration data
        
    Raises:
        ValueError: If config_id is empty or invalid
        KeyError: If configuration is not found
        TypeError: If stored data is not a dictionary
    """
    if not isinstance(config_id, str) or not config_id:
        raise ValueError("config_id must be a non-empty string")
    
    engine = _get_engine()
    with Session(engine) as session:
        stmt = (
            select(ConfigEntry)
            .where(ConfigEntry.config_id == config_id)
            .order_by(ConfigEntry.version.desc())
            .limit(1)
        )
        entry = session.execute(stmt).scalar_one_or_none()
        
        if entry is None:
            raise KeyError(f"Configuration with id '{config_id}' not found")
        
        if not isinstance(entry.config_data, dict):
            raise TypeError(f"Configuration data for '{config_id}' is not a dictionary")
        
        return entry.config_data


def save_config(config_id: str, config_data: Dict[str, Any]) -> None:
    """
    Save configuration data with versioning.
    
    Args:
        config_id: Unique identifier for the configuration
        config_data: Dictionary containing configuration data to store
        
    Raises:
        ValueError: If config_id is empty or invalid
        TypeError: If config_data is not a dictionary
    """
    if not isinstance(config_id, str) or not config_id:
        raise ValueError("config_id must be a non-empty string")
    if not isinstance(config_data, dict):
        raise TypeError("config_data must be a dictionary")
    
    engine = _get_engine()
    with Session(engine) as session:
        stmt = select(func.max(ConfigEntry.version)).where(ConfigEntry.config_id == config_id)
        max_version = session.execute(stmt).scalar()
        
        new_version = 1 if max_version is None else max_version + 1
        
        entry = ConfigEntry(
            config_id=config_id,
            version=new_version,
            config_data=config_data,
        )
        session.add(entry)
        session.commit()
        
        logger.debug(f"Saved config '{config_id}' version {new_version}")


def _selftest() -> None:
    """
    Self-test using temporary SQLite database.
    
    Verifies:
    - load_config() retrieves existing config from temp SQLite
    - save_config() persists new config and updates version
    - Config data is type-checked and validated
    - No network or external dependencies used during test
    - All database operations use select() and session methods
    - Completes in under 20 seconds with clean teardown
    """
    global _engine
    original_engine = _engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_config.db")
        db_url = f"sqlite:///{db_path}"
        
        test_engine = create_engine(db_url)
        _set_engine(test_engine)
        
        try:
            # Test save and load
            config_v1 = {"model": "resnet", "batch_size": 32, "lr": 0.01}
            save_config("model_config", config_v1)
            loaded = load_config("model_config")
            assert loaded == config_v1, f"Expected {config_v1}, got {loaded}"
            
            # Test versioning
            config_v2 = {"model": "resnet", "batch_size": 64, "lr": 0.001}
            save_config("model_config", config_v2)
            loaded_v2 = load_config("model_config")
            assert loaded_v2 == config_v2, f"Expected latest version {config_v2}, got {loaded_v2}"
            
            # Verify both versions exist in database
            with Session(test_engine) as session:
                stmt = (
                    select(ConfigEntry.version, ConfigEntry.config_data)
                    .where(ConfigEntry.config_id == "model_config")
                    .order_by(ConfigEntry.version)
                )
                results = session.execute(stmt).all()
                assert len(results) == 2, f"Expected 2 versions, got {len(results)}"
                assert results[0].version == 1
                assert results[1].version == 2
                assert results[0].config_data == config_v1
                assert results[1].config_data == config_v2
            
            # Test validation: empty config_id
            try:
                load_config("")
                assert False, "Should raise ValueError for empty config_id"
            except ValueError:
                pass
            
            try:
                save_config("", {"key": "value"})
                assert False, "Should raise ValueError for empty config_id"
            except ValueError:
                pass
            
            # Test validation: wrong type for config_data
            try:
                save_config("test", "not a dict")
                assert False, "Should raise TypeError for non-dict config_data"
            except TypeError:
                pass
            
            # Test validation: nonexistent config
            try:
                load_config("nonexistent_config_id")
                assert False, "Should raise KeyError for nonexistent config"
            except KeyError:
                pass
            
            # Test complex data types
            complex_data = {
                "layers": [64, 128, 256],
                "activation": "relu",
                "dropout": 0.5,
                "nested": {"optimizer": "adam", "params": {"beta1": 0.9}},
                "flags": {"use_bn": True, "trainable": False}
            }
            save_config("complex_cfg", complex_data)
            loaded_complex = load_config("complex_cfg")
            assert loaded_complex == complex_data
            
        finally:
            _engine = original_engine
            test_engine.dispose()


if __name__ == "__main__":
    _selftest()
