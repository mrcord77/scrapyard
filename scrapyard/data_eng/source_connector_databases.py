"""
source_connector_databases — Connect and extract data from database sources using SQLAlchemy 2.x, ensuring type safety and separation of concerns between data access and business logic.

### PART-META-JSON
{
  "name": "source_connector_databases",
  "layer": "data_eng",
  "purpose": "Connect and extract data from database sources using SQLAlchemy 2.x, ensuring type safety and separation of concerns between data access and business logic.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "extractor"
  ],
  "inputs": "Public API: query_db(sql, params); read_table(table_name, schema).",
  "outputs": "Returns: query_db -> list[dict[str, Any]]; read_table -> list[dict[str, Any]].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.data_eng.source_connector_databases`.",
  "example": "from scrapyard.data_eng.source_connector_databases import *",
  "import_path": "scrapyard.data_eng.source_connector_databases"
}
### END-PART-META
"""

import logging
import os
import tempfile
from typing import Any

from sqlalchemy import Integer, String, Text, create_engine, MetaData, select, Table, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# Module-level engine reference (not initialized at import)
_engine: Engine | None = None


def _set_engine(engine: Engine | None) -> None:
    """Internal helper to configure the module-level engine."""
    global _engine
    _engine = engine
    if engine:
        logger.info("Database engine configured")
    else:
        logger.info("Database engine cleared")


def query_db(sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    """
    Execute a SQL query and return results as a list of dictionaries.
    
    Args:
        sql: SQL query string
        params: Optional dictionary of bound parameters
        
    Returns:
        List of dictionaries representing result rows
    """
    if _engine is None:
        raise RuntimeError("Database engine not configured")
    
    logger.debug(f"Executing query: {sql[:100]}...")
    with Session(_engine) as session:
        result = session.execute(text(sql), params or {})
        rows = [dict(row) for row in result.mappings()]
        logger.info(f"query_db returned {len(rows)} rows")
        return rows


def read_table(table_name: str, schema: str | None = None) -> list[dict[str, Any]]:
    """
    Read all data from a specified table using reflection.
    
    Args:
        table_name: Name of the table to read
        schema: Optional schema name
        
    Returns:
        List of dictionaries representing table rows
    """
    if _engine is None:
        raise RuntimeError("Database engine not configured")
    
    logger.debug(f"Reading table: {table_name} (schema={schema})")
    with Session(_engine) as session:
        metadata = MetaData()
        table = Table(table_name, metadata, schema=schema, autoload_with=_engine)
        stmt = select(table)
        result = session.execute(stmt)
        rows = [dict(row) for row in result.mappings()]
        logger.info(f"read_table returned {len(rows)} rows from {table_name}")
        return rows


def _selftest() -> None:
    """
    Offline self-test using temporary SQLite database.
    Verifies query execution and table reading without network access.
    """
    logger.info("Starting _selftest")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        connection_url = f"sqlite:///{db_path}"
        
        # Create temporary SQLite engine
        test_engine = create_engine(connection_url, echo=False, future=True)
        
        try:
            _set_engine(test_engine)
            
            # Define test model using SQLAlchemy 2.x Mapped style
            class ScrapItem(IntPKModel):
                __tablename__ = "scrap_items"
                name: Mapped[str] = mapped_column(String(100), nullable=False)
                weight: Mapped[int] = mapped_column(Integer, default=0)
                notes: Mapped[str | None] = mapped_column(Text, nullable=True)
            
            # Create tables
            IntPKModel.metadata.create_all(test_engine)
            
            # Insert test data
            with Session(test_engine) as session:
                session.add_all([
                    ScrapItem(name="gear", weight=5, notes="Metal gear"),
                    ScrapItem(name="spring", weight=1, notes=None),
                    ScrapItem(name="bolt", weight=10, notes="Heavy duty"),
                ])
                session.commit()
            
            # Test query_db with parameters
            results = query_db(
                "SELECT name, weight FROM scrap_items WHERE weight > :min_weight",
                {"min_weight": 2}
            )
            assert len(results) == 2, f"Expected 2 rows, got {len(results)}"
            assert all(isinstance(r, dict) for r in results), "Results must be dicts"
            names = {r["name"] for r in results}
            assert names == {"gear", "bolt"}, f"Unexpected names: {names}"
            logger.info("query_db with params: PASS")
            
            # Test query_db without parameters
            count_res = query_db("SELECT COUNT(*) as total FROM scrap_items")
            assert len(count_res) == 1 and count_res[0]["total"] == 3
            logger.info("query_db without params: PASS")
            
            # Test read_table
            table_data = read_table("scrap_items")
            assert len(table_data) == 3, f"Expected 3 rows, got {len(table_data)}"
            assert all(isinstance(row, dict) for row in table_data)
            assert all("id" in row and "name" in row and "weight" in row for row in table_data)
            logger.info("read_table: PASS")
            
            # Verify logging occurred (implicitly verified if no exception)
            logger.info("All assertions passed")
            
        finally:
            # Cleanup: dispose engine and reset module state
            test_engine.dispose()
            _set_engine(None)
            logger.info("_selftest cleanup completed")


if __name__ == "__main__":
    _selftest()
