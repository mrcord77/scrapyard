"""
configurator — Manage and apply configuration settings across different environments, ensuring consistency and traceability. It provides a structured way to define, store, and apply configuration values with environ

### PART-META-JSON
{
  "name": "configurator",
  "layer": "devops",
  "purpose": "Manage and apply configuration settings across different environments, ensuring consistency and traceability. It provides a structured way to define, store, and apply configuration values with environ",
  "addition": true,
  "status": "core",
  "dependencies": [
    "environment_diffing_tool"
  ],
  "inputs": "Public API: apply_config(session, env, config); ConfigSetting(...).",
  "outputs": "Returns: apply_config -> None.",
  "files_created": [
    "config_setting"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.devops.configurator`.",
  "example": "from scrapyard.devops.configurator import *",
  "import_path": "scrapyard.devops.configurator"
}
### END-PART-META
"""

import logging
import tempfile
from typing import Any, Dict

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, Mapped, mapped_column
from sqlalchemy.exc import IntegrityError
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class ConfigSetting(IntPKModel):
    """Configuration setting with environment tracking."""
    __tablename__ = "config_setting"
    
    name: Mapped[str] = mapped_column(unique=True)
    value: Mapped[str]
    environment: Mapped[str]


def apply_config(session: Session, env: str, config: Dict[str, Any]) -> None:
    """Apply configuration settings for a specific environment.
    
    Args:
        session: SQLAlchemy session
        env: Environment name (e.g., 'prod', 'dev')
        config: Dictionary of configuration key-value pairs
    """
    for key, val in config.items():
        str_val = str(val)
        stmt = select(ConfigSetting).where(ConfigSetting.name == key)
        existing = session.execute(stmt).scalar_one_or_none()
        
        if existing:
            existing.value = str_val
            existing.environment = env
        else:
            setting = ConfigSetting(name=key, value=str_val, environment=env)
            session.add(setting)


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = f"{tmpdir}/test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            ConfigSetting.metadata.create_all(engine)
            
            # Test 1: ConfigSetting model can be created and queried
            with Session(engine) as session:
                setting = ConfigSetting(name="test_key", value="test_value", environment="test_env")
                session.add(setting)
                session.commit()
                
                retrieved = session.execute(
                    select(ConfigSetting).where(ConfigSetting.name == "test_key")
                ).scalar_one()
                assert retrieved.name == "test_key"
                assert retrieved.value == "test_value"
                assert retrieved.environment == "test_env"
            
            # Test 2: apply_config updates settings for a given environment
            with Session(engine) as session:
                apply_config(session, "production", {"debug_mode": "false", "timeout": "30"})
                session.commit()
                
                debug = session.execute(
                    select(ConfigSetting).where(ConfigSetting.name == "debug_mode")
                ).scalar_one()
                assert debug.value == "false"
                assert debug.environment == "production"
                
                # Update existing setting
                apply_config(session, "development", {"debug_mode": "true"})
                session.commit()
                
                debug = session.execute(
                    select(ConfigSetting).where(ConfigSetting.name == "debug_mode")
                ).scalar_one()
                assert debug.value == "true"
                assert debug.environment == "development"
            
            # Test 3: Duplicate config names raise constraint errors
            with Session(engine) as session:
                dup = ConfigSetting(name="debug_mode", value="duplicate", environment="staging")
                session.add(dup)
                try:
                    session.commit()
                    raise AssertionError("Expected IntegrityError for duplicate name")
                except IntegrityError:
                    session.rollback()
            
            # Test 4: Session operations do not commit automatically
            with Session(engine) as session:
                apply_config(session, "temp", {"uncommitted_key": "uncommitted_value"})
                # Do not commit
                
                # Verify not visible to other sessions
                with Session(engine) as session2:
                    result = session2.execute(
                        select(ConfigSetting).where(ConfigSetting.name == "uncommitted_key")
                    ).scalar_one_or_none()
                    assert result is None, "Uncommitted changes should not be visible"
                
                session.rollback()
        
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
