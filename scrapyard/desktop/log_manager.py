"""
log_manager — Manages application logging with structured storage and retrieval, ensuring logs are persisted and queryable for debugging and auditing.

### PART-META-JSON
{
  "name": "log_manager",
  "layer": "desktop",
  "purpose": "Manages application logging with structured storage and retrieval, ensuring logs are persisted and queryable for debugging and auditing.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "SQLAlchemy Session; level/message/context kwargs for log(); filter dict for get_logs().",
  "outputs": "Rows in log_manager_logs table; setup_logging() configures stdlib logging.",
  "files_created": ["optional log file when setup_logging({'filename': ...}) is used"],
  "security_notes": "Context kwargs are stored verbatim as JSON - never pass secrets/PII in log context. LogManager flushes but does not commit; the caller owns the transaction. Table is namespaced log_manager_logs on the shared Base.",
  "ai_usage": "Import what you need from `scrapyard.desktop.log_manager`.",
  "example": "from scrapyard.desktop.log_manager import *",
  "import_path": "scrapyard.desktop.log_manager"
}
### END-PART-META
"""

from sqlalchemy import String, Text, DateTime, JSON, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class Log(IntPKModel):
    """SQLAlchemy model for structured log storage."""
    __tablename__ = "log_manager_logs"
    
    level: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


def setup_logging(config: Dict[str, Any]) -> None:
    """
    Configure standard Python logging with file-based storage.
    
    Args:
        config: Dictionary with optional keys:
            - level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            - filename: Path to log file
            - format: Log format string
    """
    level = config.get('level', 'INFO')
    filename = config.get('filename')
    format_str = config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    handlers = []
    if filename:
        handlers.append(logging.FileHandler(filename))
    else:
        handlers.append(logging.StreamHandler())
    
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=format_str,
        handlers=handlers,
        force=True
    )


class LogManager:
    """
    Centralized log manager for database-backed structured logging.
    Auto-flushes on write, does not auto-commit.
    """
    
    def __init__(self, session: Session):
        """
        Initialize LogManager with a SQLAlchemy session.
        
        Args:
            session: SQLAlchemy Session for database operations
        """
        self.session = session
    
    def log(self, level: str, message: str, **kwargs) -> None:
        """
        Create a log entry and flush to database (no commit).
        
        Args:
            level: Log level (e.g., 'INFO', 'ERROR', 'DEBUG')
            message: Log message text
            **kwargs: Additional context data stored as JSON
        """
        log_entry = Log(
            level=level,
            message=message,
            created_at=datetime.now(timezone.utc),
            context=kwargs if kwargs else None
        )
        self.session.add(log_entry)
        self.session.flush()
    
    def get_logs(self, filters: Dict[str, Any]) -> List[Log]:
        """
        Query logs from database with optional filters.
        
        Args:
            filters: Dictionary of filter conditions:
                - level: Exact match on log level
                - message_contains: Substring search in message
                - since: datetime, logs created at or after this time
                - until: datetime, logs created at or before this time
        
        Returns:
            List of Log model instances matching filters, ordered by created_at desc
        """
        stmt = select(Log)
        
        if 'level' in filters:
            stmt = stmt.where(Log.level == filters['level'])
        
        if 'message_contains' in filters:
            stmt = stmt.where(Log.message.contains(filters['message_contains']))
        
        if 'since' in filters:
            stmt = stmt.where(Log.created_at >= filters['since'])
        
        if 'until' in filters:
            stmt = stmt.where(Log.created_at <= filters['until'])
        
        stmt = stmt.order_by(Log.created_at.desc())
        result = self.session.execute(stmt)
        return list(result.scalars().all())


def _selftest():
    """
    Self-test for log_manager module.
    Verifies LogManager, setup_logging, database storage, and filtering.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Setup test database
        db_path = os.path.join(tmpdir, "test_logs.db")
        engine = create_engine(f"sqlite:///{db_path}")
        Log.metadata.create_all(engine)
        
        # Test setup_logging with file output
        log_file = os.path.join(tmpdir, "app.log")
        setup_logging({
            'level': 'DEBUG',
            'filename': log_file,
            'format': '%(message)s'
        })
        
        test_logger = logging.getLogger("selftest")
        test_logger.info("LOGGING_SETUP_VERIFIED")
        
        with open(log_file, 'r') as f:
            file_content = f.read()
            assert "LOGGING_SETUP_VERIFIED" in file_content, "setup_logging must configure file handler"
        
        # Test LogManager functionality
        with Session(engine) as session:
            manager = LogManager(session)
            
            # Create logs with different levels and contexts
            manager.log("INFO", "Application started", user_id=1, action="boot")
            manager.log("ERROR", "Connection failed", error_code=500, retry=True)
            manager.log("INFO", "Application shutdown", user_id=1, action="shutdown")
            
            # Verify logs stored via flush (visible in same uncommitted session)
            count_result = session.execute(select(Log)).scalars().all()
            assert len(count_result) == 3, f"Expected 3 logs, got {len(count_result)}"
            
            # Test level filter
            info_logs = manager.get_logs({'level': 'INFO'})
            assert len(info_logs) == 2, f"Expected 2 INFO logs, got {len(info_logs)}"
            
            error_logs = manager.get_logs({'level': 'ERROR'})
            assert len(error_logs) == 1, f"Expected 1 ERROR log, got {len(error_logs)}"
            assert error_logs[0].message == "Connection failed"
            
            # Test message contains filter
            conn_logs = manager.get_logs({'message_contains': 'Connection'})
            assert len(conn_logs) == 1, "Should filter by message content"
            
            # Test datetime filters using timedelta
            five_mins_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
            five_mins_future = datetime.now(timezone.utc) + timedelta(minutes=5)
            
            recent_logs = manager.get_logs({'since': five_mins_ago})
            assert len(recent_logs) == 3, "Should find all recent logs"
            
            old_logs = manager.get_logs({'until': five_mins_ago})
            assert len(old_logs) == 0, "Should find no old logs"
            
            future_logs = manager.get_logs({'since': five_mins_future})
            assert len(future_logs) == 0, "Should find no future logs"
            
            # Verify log structure
            log_entry = info_logs[0]
            assert isinstance(log_entry.id, int), "Log must have integer primary key"
            assert log_entry.level == "INFO"
            assert isinstance(log_entry.created_at, datetime), "Log must have datetime"
            assert log_entry.context is not None, "Context should be stored"
            assert log_entry.context.get('user_id') == 1, "Context JSON must preserve data"
        
        # Cleanup connections
        engine.dispose()
    
    print("log_manager._selftest: PASSED")


if __name__ == "__main__":
    _selftest()
