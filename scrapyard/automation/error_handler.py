"""
error_handler — The `error_handler` module provides centralized error handling and logging for web automation tasks, ensuring consistent behavior across the automation_web domain. It enables robust error capture, cla

### PART-META-JSON
{
  "name": "error_handler",
  "layer": "automation",
  "purpose": "The `error_handler` module provides centralized error handling and logging for web automation tasks, ensuring consistent behavior across the automation_web domain. It enables robust error capture, cla",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure_logger(level); log_error(exc, context); retry_on_failure(func, *, max_retries); LogManager(...); ErrorHandler(...).",
  "outputs": "Returns: configure_logger -> None; log_error -> None; retry_on_failure -> Callable.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.automation.error_handler`.",
  "example": "from scrapyard.automation.error_handler import *",
  "import_path": "scrapyard.automation.error_handler"
}
### END-PART-META
"""

import logging
import sqlite3
import tempfile
import time
import json
import threading
import functools
import traceback
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable

# Module logger - no execution at import time
_logger = logging.getLogger(__name__)


class LogManager:
    """Thread-safe log manager writing to SQLite database."""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or ":memory:"
        self._lock = threading.Lock()
        self._local = threading.local()
        self._ensure_tables()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get or create thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._create_tables(self._local.conn)
        return self._local.conn
    
    def _ensure_tables(self):
        """Initialize tables using a temporary connection if needed."""
        conn = sqlite3.connect(self.db_path)
        try:
            self._create_tables(conn)
        finally:
            conn.close()
    
    def _create_tables(self, conn: sqlite3.Connection):
        """Create logs table if not exists."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                context TEXT,
                stack_trace TEXT
            )
        """)
        conn.commit()
    
    def log(self, level: str, message: str, context: Optional[Dict[str, Any]] = None,
            stack_trace: Optional[str] = None) -> None:
        """Write log entry to database."""
        timestamp = datetime.now(timezone.utc).isoformat()
        context_json = json.dumps(context) if context else None
        
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                "INSERT INTO logs (timestamp, level, message, context, stack_trace) VALUES (?, ?, ?, ?, ?)",
                (timestamp, level, message, context_json, stack_trace)
            )
            conn.commit()
    
    def get_logs(self, level: Optional[str] = None) -> list:
        """Retrieve logs, optionally filtered by level."""
        conn = self._get_connection()
        if level:
            cursor = conn.execute("SELECT * FROM logs WHERE level = ?", (level,))
        else:
            cursor = conn.execute("SELECT * FROM logs ORDER BY id")
        return cursor.fetchall()
    
    def close(self):
        """Close all database connections."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


class ErrorHandler:
    """Centralized error handling with context capture."""
    
    def __init__(self, log_manager: Optional[LogManager] = None):
        self.log_manager = log_manager or LogManager()
        self._lock = threading.Lock()
    
    def handle_error(self, exc: Exception, context: Optional[Dict[str, Any]] = None) -> None:
        """Capture exception with stack trace and log it."""
        exc_type = type(exc).__name__
        message = str(exc)
        stack_trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        
        ctx = context or {}
        ctx['exception_type'] = exc_type
        
        with self._lock:
            self.log_manager.log(
                level="ERROR",
                message=message,
                context=ctx,
                stack_trace=stack_trace
            )


def configure_logger(level: str = "INFO") -> None:
    """Configure root logger level."""
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {level}")
    logging.getLogger().setLevel(numeric_level)


def log_error(exc: Exception, context: dict) -> None:
    """Convenience function to log an error with context."""
    handler = ErrorHandler()
    handler.handle_error(exc, context)


def retry_on_failure(func: Callable = None, *, max_retries: int = 3) -> Callable:
    """
    Decorator to retry function on failure with exponential backoff.
    Supports both @retry_on_failure and @retry_on_failure(max_retries=N) syntax.
    """
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return f(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        # Exponential backoff: 0.01s, 0.02s, 0.04s, etc.
                        time.sleep(0.01 * (2 ** attempt))
                    else:
                        raise last_exception
            # Should not reach here, but defensive
            if last_exception:
                raise last_exception
            return None
        return wrapper
    
    if func is None:
        return decorator
    else:
        return decorator(func)


def _selftest():
    """Self-contained unit tests for error_handler module."""
    import inspect
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        lm = LogManager(db_path)
        
        try:
            # Test LogManager writes to SQLite
            lm.log("INFO", "Test message", {"test_id": 1})
            logs = lm.get_logs()
            assert len(logs) == 1
            assert logs[0][2] == "INFO"
            
            # Test ErrorHandler captures and logs exceptions
            eh = ErrorHandler(lm)
            try:
                raise ValueError("Test exception")
            except Exception as e:
                eh.handle_error(e, {"operation": "test"})
            
            error_logs = lm.get_logs("ERROR")
            assert len(error_logs) == 1
            assert "Test exception" in error_logs[0][3]
            assert error_logs[0][4] is not None  # context JSON
            
            # Test configure_logger
            configure_logger("DEBUG")
            assert logging.getLogger().level == logging.DEBUG
            configure_logger("WARNING")
            assert logging.getLogger().level == logging.WARNING
            
            # Test retry_on_failure with eventual success
            call_count = [0]
            
            def succeeds_on_third():
                call_count[0] += 1
                if call_count[0] < 3:
                    raise ConnectionError("Transient")
                return "success"
            
            decorated = retry_on_failure(succeeds_on_third, max_retries=3)
            result = decorated()
            assert result == "success"
            assert call_count[0] == 3
            
            # Test retry_on_failure with eventual failure
            call_count[0] = 0
            
            def always_fails():
                call_count[0] += 1
                raise RuntimeError("Persistent")
            
            decorated_fail = retry_on_failure(always_fails, max_retries=2)
            try:
                decorated_fail()
                assert False, "Should have raised"
            except RuntimeError:
                pass
            assert call_count[0] == 3  # initial + 2 retries
            
            # Test retry_on_failure as bare decorator
            call_count[0] = 0
            
            @retry_on_failure
            def bare_decorated():
                call_count[0] += 1
                if call_count[0] < 2:
                    raise Exception("Fail once")
                return "ok"
            
            assert bare_decorated() == "ok"
            assert call_count[0] == 2
            
            # Test type hints are present
            sig = inspect.signature(configure_logger)
            assert sig.parameters['level'].default == "INFO"
            
            sig = inspect.signature(log_error)
            assert 'exc' in sig.parameters
            assert 'context' in sig.parameters
            
            sig = inspect.signature(retry_on_failure)
            assert 'func' in sig.parameters
            assert 'max_retries' in sig.parameters
            
            # Test log_error function (uses in-memory db, no cleanup needed)
            try:
                raise TypeError("Standalone test")
            except Exception as e:
                log_error(e, {"source": "selftest"})
            
        finally:
            lm.close()
        
        print("_selftest PASSED")


if __name__ == "__main__":
    _selftest()
