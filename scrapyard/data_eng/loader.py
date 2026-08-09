"""
loader — ** The `scrapyard.data_eng.loader` module provides reusable functionality to load transformed data into target storage systems such as databases or files, ensuring consistency and reliability in data 

### PART-META-JSON
{
  "name": "loader",
  "layer": "data_eng",
  "purpose": "Provides reusable functionality to load transformed data into target storage systems such as databases or files, ensuring consistency and reliability in data.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: load_to_db(session, data, model); write_to_file(data, path, format).",
  "outputs": "Returns: load_to_db -> None; write_to_file -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.data_eng.loader`.",
  "example": "from scrapyard.data_eng.loader import *",
  "import_path": "scrapyard.data_eng.loader"
}
### END-PART-META
"""

import csv
import json
import logging
import os
import sqlite3
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from sqlalchemy import Boolean, Float, String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

# Lazy imports: pandas is loaded only in _write_parquet when needed
logger = logging.getLogger(__name__)

PART_META = {
    "name": "loader",
    "layer": "data_eng"
}


def load_to_db(session: Session, data: List[Dict[str, Any]], model: Type[Any]) -> None:
    """Load transformed data into database using the provided session.
    
    Args:
        session: SQLAlchemy 2.x Session instance
        data: List of dictionaries representing model instances
        model: SQLAlchemy model class to instantiate
        
    Note:
        This function performs a flush() but does not commit.
        The caller is responsible for committing or rolling back the transaction.
    """
    if not data:
        logger.debug("No data provided to load_to_db")
        return
    
    logger.info(f"Preparing to load {len(data)} records into {model.__name__}")
    
    for idx, record in enumerate(data):
        try:
            instance = model(**record)
            session.add(instance)
        except Exception as e:
            logger.error(f"Failed to create instance at index {idx}: {e}")
            raise
    
    session.flush()
    logger.info(f"Flushed {len(data)} records to database session")


def write_to_file(data: List[Dict[str, Any]], path: str, format: str = "parquet") -> None:
    """Write data to a file in the specified format.
    
    Args:
        data: List of dictionaries to write
        path: Target file path
        format: File format - one of "csv", "json", "parquet" (default: "parquet")
        
    Raises:
        ValueError: If format is not supported
        ImportError: If required dependencies for parquet are not installed
    """
    logger.info(f"Writing {len(data)} records to {path} (format: {format})")
    
    format_lower = format.lower()
    
    if format_lower == "csv":
        _write_csv(data, path)
    elif format_lower == "json":
        _write_json(data, path)
    elif format_lower == "parquet":
        _write_parquet(data, path)
    else:
        raise ValueError(f"Unsupported format '{format}'. Use: csv, json, parquet")
    
    logger.debug(f"Successfully wrote data to {path}")


def _write_csv(data: List[Dict[str, Any]], path: str) -> None:
    """Helper to write CSV files."""
    if not data:
        with open(path, "w", encoding="utf-8") as f:
            pass
        return
    
    with open(path, "w", newline="", encoding="utf-8") as f:
        fieldnames = list(data[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)


def _write_json(data: List[Dict[str, Any]], path: str) -> None:
    """Helper to write JSON files."""
    class CustomEncoder(json.JSONEncoder):
        def default(self, obj: Any) -> Any:
            if isinstance(obj, datetime):
                return obj.isoformat()
            return super().default(obj)
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, cls=CustomEncoder)


def _write_parquet(data: List[Dict[str, Any]], path: str) -> None:
    """Helper to write Parquet files using pandas."""
    try:
        import pandas as pd
    except ImportError as e:
        raise ImportError("pandas is required for parquet support") from e
    
    df = pd.DataFrame(data)
    df.to_parquet(path, index=False)


def _selftest() -> None:
    """Offline self-test validating loader functionality.
    
    Uses temporary SQLite database and temporary directory for file operations.
    Must complete in under 20 seconds.
    """
    logger.info("Starting loader module self-test")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Test data
        test_records = [
            {"id": 1, "name": "alpha", "score": 95.5, "active": True},
            {"id": 2, "name": "beta", "score": 87.0, "active": False},
            {"id": 3, "name": "gamma", "score": None, "active": True},
        ]
        
        # Test CSV
        csv_path = os.path.join(tmpdir, "test.csv")
        write_to_file(test_records, csv_path, "csv")
        assert os.path.exists(csv_path), "CSV file was not created"
        
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
            assert rows[0]["name"] == "alpha", "CSV data mismatch"
        
        # Test JSON
        json_path = os.path.join(tmpdir, "test.json")
        write_to_file(test_records, json_path, "json")
        assert os.path.exists(json_path), "JSON file was not created"
        
        with open(json_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            assert len(loaded) == 3, f"Expected 3 records, got {len(loaded)}"
            assert loaded[1]["score"] == 87.0, "JSON data mismatch"
        
        # Test Parquet
        try:
            import pandas as pd
            parquet_path = os.path.join(tmpdir, "test.parquet")
            write_to_file(test_records, parquet_path, "parquet")
            assert os.path.exists(parquet_path), "Parquet file was not created"
            
            df = pd.read_parquet(parquet_path)
            assert len(df) == 3, f"Expected 3 rows in parquet, got {len(df)}"
            assert "name" in df.columns, "Parquet missing expected columns"
        except ImportError:
            logger.warning("pandas not available, skipping parquet test")
        
        # Test Database loading
        from scrapyard.database.base_model import IntPKModel
        
        db_path = os.path.join(tmpdir, "test.db")
        
        # Verify SQLite connectivity and close immediate connection
        conn = sqlite3.connect(db_path)
        conn.close()
        
        engine = create_engine(f"sqlite:///{db_path}")
        
        class TestItem(IntPKModel):
            __tablename__ = "loader_test_items"
            name: Mapped[str] = mapped_column(String(50))
            score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
            active: Mapped[bool] = mapped_column(Boolean, default=True)
        
        # Create tables
        from sqlalchemy.orm import declarative_base
        Base = declarative_base(metadata=IntPKModel.metadata)
        Base.metadata.create_all(engine)
        
        with Session(engine) as session:
            load_to_db(session, test_records, TestItem)
            
            # Verify flush worked by querying within same session
            stmt = select(TestItem).where(TestItem.name == "beta")
            result = session.execute(stmt).scalar_one()
            assert result.score == 87.0, "Database load mismatch"
            assert result.active is False, "Boolean field mismatch"
            
            # Verify all records present
            all_items = session.execute(select(TestItem)).scalars().all()
            assert len(all_items) == 3, f"Expected 3 items in DB, got {len(all_items)}"
            
            session.commit()
        
        engine.dispose()
        logger.info("Database test completed successfully")
    
    logger.info("Loader self-test completed successfully")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
