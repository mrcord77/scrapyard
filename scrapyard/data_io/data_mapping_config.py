"""
data_mapping_config — ** Define and manage mappings between data fields and domain models for consistent data import/export. This module provides a reusable configuration system for aligning external data with internal dom

### PART-META-JSON
{
  "name": "data_mapping_config",
  "layer": "data_io",
  "purpose": "Define and manage mappings between data fields and domain models for consistent data import/export. This module provides a reusable configuration system for aligning external data with internal dom.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: validate_mapping(mapping); MappingConfig(...).",
  "outputs": "Returns: validate_mapping -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.data_io.data_mapping_config`.",
  "example": "from scrapyard.data_io.data_mapping_config import *",
  "import_path": "scrapyard.data_io.data_mapping_config"
}
### END-PART-META
"""
from sqlalchemy import String, Integer, JSON, select, create_engine, text
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
from typing import Dict, Any, Optional
import os
import logging
import tempfile

logger = logging.getLogger(__name__)


class MappingConfig(IntPKModel):
    """
    SQLAlchemy ORM model for storing field mapping configurations.
    
    Maps external data field names to internal domain model field names
    for consistent data import/export operations.
    """
    __tablename__ = 'mapping_config'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    domain_model: Mapped[str] = mapped_column(String(255), nullable=False)
    field_mapping: Mapped[Dict[str, str]] = mapped_column(JSON, nullable=False)
    
    def __init__(self, name: str, domain_model: str, field_mapping: Dict[str, str], **kwargs: Any) -> None:
        """
        Initialize a MappingConfig instance.
        
        Args:
            name: Unique identifier for this mapping configuration
            domain_model: Target domain model class name
            field_mapping: Dictionary mapping external field names to internal field names
            **kwargs: Additional arguments passed to parent class
        """
        super().__init__(**kwargs)
        self.name = name
        self.domain_model = domain_model
        self.field_mapping = field_mapping


def validate_mapping(mapping: Dict[str, Any]) -> None:
    """
    Validate that a field mapping structure is valid.
    
    Args:
        mapping: Dictionary to validate
        
    Raises:
        ValueError: If mapping is not a dict or contains non-string keys/values
    """
    if not isinstance(mapping, dict):
        raise ValueError("Mapping must be a dictionary")
    
    for key, value in mapping.items():
        if not isinstance(key, str):
            raise ValueError(f"Mapping key must be a string, got {type(key).__name__}: {key}")
        if not isinstance(value, str):
            raise ValueError(f"Mapping value must be a string, got {type(value).__name__}: {value}")


def _selftest() -> None:
    """
    Offline self-test using temporary SQLite database.
    
    Validates:
    - MappingConfig creation and persistence
    - validate_mapping behavior with valid and invalid inputs
    - Session-based CRUD operations
    - Rollback functionality
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_file = os.path.join(temp_dir, 'test.db')
        engine = create_engine(f'sqlite:///{db_file}', echo=False)
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        
        try:
            # Create tables
            IntPKModel.metadata.create_all(engine)
            
            # Enable foreign keys
            with SessionLocal() as session:
                session.execute(text('PRAGMA foreign_keys=ON'))
                session.commit()
            
            # Test validate_mapping with valid structure
            validate_mapping({'external_field': 'internal_field'})
            logger.info("Valid mapping structure accepted")
            
            # Test validate_mapping with invalid value type (should raise ValueError)
            try:
                validate_mapping({'invalid_entry': 123})
                raise AssertionError("validate_mapping should have raised ValueError for non-string value")
            except ValueError as e:
                logger.info(f"Invalid mapping correctly rejected: {e}")
            
            # Test validate_mapping with non-dict (should raise ValueError)
            try:
                validate_mapping("not a dict")
                raise AssertionError("validate_mapping should have raised ValueError for non-dict")
            except ValueError as e:
                logger.info(f"Non-dict mapping correctly rejected: {e}")
            
            # Create and save MappingConfig instance
            mc = MappingConfig(
                name='test_mapping',
                domain_model='TestModel',
                field_mapping={'external_field': 'internal_field'}
            )
            
            with SessionLocal() as session:
                session.add(mc)
                session.commit()
                created_id = mc.id
                assert created_id is not None, "MappingConfig should have an ID after commit"
            
            # Query and validate saved instance
            with SessionLocal() as session:
                stmt = select(MappingConfig).where(MappingConfig.name == 'test_mapping')
                loaded_mc: Optional[MappingConfig] = session.execute(stmt).scalar_one_or_none()
                
                assert loaded_mc is not None, "MappingConfig could not be retrieved from database"
                assert loaded_mc.field_mapping == {'external_field': 'internal_field'}, "Field mapping does not match"
                assert loaded_mc.domain_model == 'TestModel', "Domain model does not match"
                assert loaded_mc.name == 'test_mapping', "Name does not match"
                logger.info("MappingConfig persistence verified")
            
            # Test session-based CRUD without commit (rollback)
            with SessionLocal() as session:
                mc_temp = MappingConfig(
                    name='temp_rollback_test',
                    domain_model='TempModel',
                    field_mapping={'temp_field': 'temp_internal'}
                )
                session.add(mc_temp)
                # Verify it's pending in the session
                assert mc_temp in session.new, "Object should be in session.new before commit"
                session.rollback()
            
            # Verify rolled-back entity is not in database
            with SessionLocal() as session:
                stmt = select(MappingConfig).where(MappingConfig.name == 'temp_rollback_test')
                loaded_temp: Optional[MappingConfig] = session.execute(stmt).scalar_one_or_none()
                assert loaded_temp is None, "Rolled-back MappingConfig should not exist in database"
            
            logger.info("Self-test successful: all assertions passed")
            
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
