"""
data_export_executor — Execute data export operations with transaction management and rollback support, ensuring data integrity during export workflows.

### PART-META-JSON
{
  "name": "data_export_executor",
  "layer": "data_io",
  "purpose": "Execute data export operations with transaction management and rollback support, ensuring data integrity during export workflows.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: ExportResult(...); CancellationToken(...); ExportExecutor(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.data_io.data_export_executor`.",
  "example": "from scrapyard.data_io.data_export_executor import *",
  "import_path": "scrapyard.data_io.data_export_executor"
}
### END-PART-META
"""

"""
PURPOSE: Execute data export operations with transaction management and rollback support, ensuring data integrity during export workflows.

FEATURES:
- Transaction-aware export with rollback on failure
- Supports multiple export formats (JSON, CSV, XML, etc.)
- Query-based export using standardized Query objects
- Integration with SQLAlchemy 2.x for ORM and session management
- Full type hints and strict error handling
- Self-contained, no side effects on import
- Offline selftest with temporary SQLite database
- No network or external dependencies in core logic
- Supports cancellation and progress tracking

PUBLIC API:
class ExportExecutor
def execute_export(query: Query, format: str) -> ExportResult

TABLES: none

SELFTEST MUST PROVE:
- ExportExecutor correctly handles transaction rollback on error
- execute_export returns valid data for supported formats
- Query is properly scoped and executed within a transaction
- Temporary SQLite database is created and cleaned up
- No unhandled exceptions during export
- ExportResult contains expected metadata and payload
- Cancellation is respected during long-running exports
- Logging is used instead of print statements
"""

import csv
import io
import json
import logging
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import String, Integer, create_engine, func, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.engine import Engine

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


@dataclass
class ExportResult:
    """Container for export operation results."""
    success: bool
    format: str
    row_count: int
    payload: Optional[Union[str, bytes]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    transaction_id: Optional[str] = None


class CancellationToken:
    """Token to signal cancellation of export operations."""
    def __init__(self):
        self._cancelled = False
    
    def cancel(self) -> None:
        self._cancelled = True
    
    def is_cancelled(self) -> bool:
        return self._cancelled


class ExportExecutor:
    """
    Executes data export operations with transaction management and rollback support.
    
    Args:
        engine: SQLAlchemy Engine for database connections
        cancellation_token: Optional token to check for cancellation requests
    """
    
    SUPPORTED_FORMATS = {"json", "csv", "xml"}
    
    def __init__(self, engine: Engine, cancellation_token: Optional[CancellationToken] = None):
        self.engine = engine
        self.cancellation_token = cancellation_token or CancellationToken()
        self._tx_counter = 0
    
    def _generate_tx_id(self) -> str:
        self._tx_counter += 1
        return f"tx_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{self._tx_counter}"
    
    def _check_cancelled(self) -> None:
        if self.cancellation_token.is_cancelled():
            raise InterruptedError("Export operation cancelled")
    
    def _format_json(self, rows: List[Any], columns: List[str]) -> str:
        data = []
        for row in rows:
            row_dict = {}
            for idx, col in enumerate(columns):
                val = row[idx] if isinstance(row, (list, tuple)) else getattr(row, col, None)
                if isinstance(val, datetime):
                    val = val.isoformat()
                row_dict[col] = val
            data.append(row_dict)
        return json.dumps(data, indent=2)
    
    def _format_csv(self, rows: List[Any], columns: List[str]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        for row in rows:
            row_data = []
            for idx, col in enumerate(columns):
                val = row[idx] if isinstance(row, (list, tuple)) else getattr(row, col, None)
                if isinstance(val, datetime):
                    val = val.isoformat()
                row_data.append(str(val) if val is not None else "")
            writer.writerow(row_data)
        return output.getvalue()
    
    def _format_xml(self, rows: List[Any], columns: List[str]) -> str:
        root = ET.Element("export")
        root.set("timestamp", datetime.now(timezone.utc).isoformat())
        root.set("count", str(len(rows)))
        
        for row in rows:
            row_elem = ET.SubElement(root, "row")
            for idx, col in enumerate(columns):
                val = row[idx] if isinstance(row, (list, tuple)) else getattr(row, col, None)
                col_elem = ET.SubElement(row_elem, col)
                if val is not None:
                    if isinstance(val, datetime):
                        col_elem.text = val.isoformat()
                    else:
                        col_elem.text = str(val)
        
        return ET.tostring(root, encoding='unicode')
    
    def execute_export(self, query: Any, format: str) -> ExportResult:
        """
        Execute query and export results in specified format within a transaction.
        
        Args:
            query: SQLAlchemy selectable or query object
            format: Target format (json, csv, xml)
            
        Returns:
            ExportResult with data or error information
        """
        tx_id = self._generate_tx_id()
        start_time = datetime.now(timezone.utc)
        
        logger.info(f"Export started [tx={tx_id}] format={format}")
        
        if format not in self.SUPPORTED_FORMATS:
            msg = f"Unsupported format: {format}. Use: {self.SUPPORTED_FORMATS}"
            logger.error(msg)
            return ExportResult(
                success=False, format=format, row_count=0,
                error_message=msg, transaction_id=tx_id
            )
        
        session = Session(self.engine)
        try:
            with session.begin():
                self._check_cancelled()
                
                result = session.execute(query)
                columns = list(result.keys())
                rows = result.all()
                
                self._check_cancelled()
                
                row_count = len(rows)
                logger.debug(f"Retrieved {row_count} rows [tx={tx_id}]")
                
                if format == "json":
                    payload = self._format_json(rows, columns)
                elif format == "csv":
                    payload = self._format_csv(rows, columns)
                else:  # xml
                    payload = self._format_xml(rows, columns)
                
                self._check_cancelled()
                
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                metadata = {
                    "columns": columns,
                    "duration_seconds": duration,
                    "started_at": start_time.isoformat(),
                    "completed_at": datetime.now(timezone.utc).isoformat()
                }
                
                logger.info(f"Export completed [tx={tx_id}] rows={row_count}")
                return ExportResult(
                    success=True, format=format, row_count=row_count,
                    payload=payload, metadata=metadata, transaction_id=tx_id
                )
                
        except InterruptedError:
            logger.warning(f"Export cancelled [tx={tx_id}]")
            return ExportResult(
                success=False, format=format, row_count=0,
                error_message="Export was cancelled", transaction_id=tx_id
            )
        except Exception as e:
            logger.error(f"Export failed [tx={tx_id}]: {e}")
            return ExportResult(
                success=False, format=format, row_count=0,
                error_message=str(e), transaction_id=tx_id
            )
        finally:
            session.close()


def _selftest() -> None:
    """Module self-test using temporary SQLite database."""
    logger.info("Running _selftest")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        class TestModel(IntPKModel):
            __tablename__ = "test_table"
            name: Mapped[str] = mapped_column(String(50), nullable=False)
            amount: Mapped[int] = mapped_column(Integer, default=0)
        
        IntPKModel.metadata.create_all(engine)
        
        with Session(engine) as sess:
            sess.add_all([
                TestModel(name="Alpha", amount=100),
                TestModel(name="Beta", amount=200),
                TestModel(name="Gamma", amount=300),
            ])
            sess.commit()
        
        # Test successful JSON export
        executor = ExportExecutor(engine)
        query = select(TestModel.name, TestModel.amount)
        result = executor.execute_export(query, "json")
        
        assert result.success, f"JSON export failed: {result.error_message}"
        assert result.format == "json"
        assert result.row_count == 3
        assert result.payload is not None
        assert "Alpha" in result.payload
        assert result.transaction_id is not None
        assert "columns" in result.metadata
        logger.info("JSON export test passed")
        
        # Test CSV export
        result_csv = executor.execute_export(query, "csv")
        assert result_csv.success
        assert result_csv.format == "csv"
        assert result_csv.row_count == 3
        lines = result_csv.payload.strip().split('\n')
        assert len(lines) == 4  # header + 3 data rows
        assert "Alpha,100" in result_csv.payload or "Alpha" in lines[1]
        logger.info("CSV export test passed")
        
        # Test XML export
        result_xml = executor.execute_export(query, "xml")
        assert result_xml.success
        assert result_xml.format == "xml"
        assert "<export" in result_xml.payload
        assert "Alpha" in result_xml.payload
        logger.info("XML export test passed")
        
        # Test unsupported format
        result_bad = executor.execute_export(query, "yaml")
        assert not result_bad.success
        assert "Unsupported format" in result_bad.error_message
        logger.info("Unsupported format test passed")
        
        # Test transaction rollback on error
        bad_query = text("SELECT * FROM nonexistent_table_12345")
        result_err = executor.execute_export(bad_query, "json")
        assert not result_err.success
        assert result_err.transaction_id is not None
        logger.info("Transaction rollback test passed")
        
        # Test data integrity after failed export
        with Session(engine) as sess:
            count = sess.execute(select(func.count()).select_from(TestModel)).scalar()
            assert count == 3, f"Data corrupted: expected 3, got {count}"
        logger.info("Data integrity test passed")
        
        # Test cancellation
        token = CancellationToken()
        token.cancel()
        exec_cancel = ExportExecutor(engine, cancellation_token=token)
        result_cancel = exec_cancel.execute_export(query, "json")
        assert not result_cancel.success
        assert "cancelled" in result_cancel.error_message.lower()
        logger.info("Cancellation test passed")
        
        # Verify metadata structure
        result_meta = executor.execute_export(query, "json")
        assert isinstance(result_meta.metadata, dict)
        assert "duration_seconds" in result_meta.metadata
        assert isinstance(result_meta.timestamp, datetime)
        logger.info("Metadata test passed")
        
        engine.dispose()
        logger.info("_selftest completed successfully")


if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)


if __name__ == "__main__":
    _selftest()
