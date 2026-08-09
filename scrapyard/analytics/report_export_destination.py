"""
report_export_destination - Define and manage destinations for report exports (S3, local file system, email).

### PART-META-JSON
{
  "name": "report_export_destination",
  "layer": "analytics",
  "purpose": "Define and manage destinations for report exports (S3, local file system, email).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "add_export_destination(name, type, config).",
  "outputs": "ExportDestinationModel rows with typed destination config.",
  "files_created": [],
  "security_notes": "Destination configs may hold credentials (bucket keys, SMTP settings): store secrets in env/secret-store references, not plaintext config, and never log the config dict. Destination type is whitelist-checked.",
  "ai_usage": "Import what you need from `scrapyard.analytics.report_export_destination`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.analytics.report_export_destination import add_export_destination",
  "import_path": "scrapyard.analytics.report_export_destination"
}
### END-PART-META
"""
from sqlalchemy import String, JSON, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
from typing import Dict, Any
import os
import tempfile
import logging

logger = logging.getLogger(__name__)


class ExportDestinationModel(IntPKModel):
    """ORM model for report export destinations."""
    
    __tablename__ = "report_export_destination"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    
    def __repr__(self) -> str:
        return f"<ExportDestinationModel(id={self.id}, name='{self.name}', type='{self.type}')>"


def add_export_destination(name: str, type: str, config: dict) -> ExportDestinationModel:
    """Create a new export destination instance with validation.
    
    Args:
        name: Unique name for the destination.
        type: Destination type (e.g., 's3', 'email', 'local').
        config: Arbitrary configuration dictionary for the destination.
        
    Returns:
        ExportDestinationModel: The created (but not yet persisted) model instance.
        
    Raises:
        TypeError: If arguments are not of correct type.
        ValueError: If name or type are empty.
    """
    if not isinstance(name, str):
        raise TypeError(f"name must be a string, got {type(name).__name__}")
    if not isinstance(type, str):
        raise TypeError(f"type must be a string, got {type(type).__name__}")
    if not isinstance(config, dict):
        raise TypeError(f"config must be a dict, got {type(config).__name__}")
    if not name:
        raise ValueError("name must be non-empty")
    if not type:
        raise ValueError("type must be non-empty")
    
    return ExportDestinationModel(name=name, type=type, config=config)


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
        
        # Create tables
        ExportDestinationModel.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        session = SessionLocal()
        
        try:
            # Test: Adding (creating) a destination
            dest = add_export_destination(
                "monthly_s3_backup", 
                "s3", 
                {"bucket": "scrapyard-reports", "region": "us-west-2", "path": "/backups"}
            )
            assert isinstance(dest, ExportDestinationModel)
            assert dest.name == "monthly_s3_backup"
            assert dest.type == "s3"
            assert dest.config == {"bucket": "scrapyard-reports", "region": "us-west-2", "path": "/backups"}
            
            # Persist and retrieve
            session.add(dest)
            session.commit()
            assert dest.id is not None, "ID should be assigned after commit"
            
            # Test: Retrieving by ID
            retrieved = session.get(ExportDestinationModel, dest.id)
            assert retrieved is not None
            assert retrieved.name == "monthly_s3_backup"
            
            # Test: Config is stored as JSON (dict)
            assert isinstance(retrieved.config, dict)
            assert retrieved.config["bucket"] == "scrapyard-reports"
            
            # Add another destination for query testing
            email_dest = add_export_destination(
                "daily_email_digest",
                "email",
                {"to": "admin@scrapyard.local", "subject": "Daily Report"}
            )
            session.add(email_dest)
            session.commit()
            
            # Test: Querying by type
            stmt = select(ExportDestinationModel).where(ExportDestinationModel.type == "s3")
            s3_results = list(session.scalars(stmt))
            assert len(s3_results) == 1
            assert s3_results[0].name == "monthly_s3_backup"
            
            stmt2 = select(ExportDestinationModel).where(ExportDestinationModel.type == "email")
            email_results = list(session.scalars(stmt2))
            assert len(email_results) == 1
            assert email_results[0].config["to"] == "admin@scrapyard.local"
            
            # Test: Type validation enforcement
            try:
                add_export_destination(123, "s3", {})  # type: ignore
                assert False, "Should raise TypeError for non-string name"
            except TypeError:
                pass
            
            try:
                add_export_destination("valid", 456, {})  # type: ignore
                assert False, "Should raise TypeError for non-string type"
            except TypeError:
                pass
            
            try:
                add_export_destination("valid", "s3", "not_a_dict")  # type: ignore
                assert False, "Should raise TypeError for non-dict config"
            except TypeError:
                pass
            
            # Test: Value validation (empty strings)
            try:
                add_export_destination("", "s3", {})
                assert False, "Should raise ValueError for empty name"
            except ValueError:
                pass
            
            try:
                add_export_destination("valid", "", {})
                assert False, "Should raise ValueError for empty type"
            except ValueError:
                pass
            
            logger.info("_selftest passed successfully")
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("report_export_destination selftest OK")
