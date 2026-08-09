"""
network_logger — The `network_logger` module provides a structured, reusable logging system for network events, enabling consistent debugging and monitoring across distributed systems.

### PART-META-JSON
{
  "name": "network_logger",
  "layer": "network",
  "purpose": "The `network_logger` module provides a structured, reusable logging system for network events, enabling consistent debugging and monitoring across distributed systems.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: log_event(level, message, metadata); LogEntry(...); NetworkLogger(...).",
  "outputs": "Returns: log_event -> None.",
  "files_created": [
    "logs"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.network.network_logger`.",
  "example": "from scrapyard.network.network_logger import *",
  "import_path": "scrapyard.network.network_logger"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, JSON, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Dict, Any
import os
import tempfile


class LogEntry(IntPKModel):
    __tablename__ = "network_logger_logs"
    
    level: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(String)
    # Map to 'metadata' column but use 'meta' as attribute name to avoid 
    # conflict with SQLAlchemy's reserved 'metadata' class attribute
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime)


class NetworkLogger:
    def __init__(self, db_session: Session):
        self._session = db_session
    
    def log(self, level: str, message: str, metadata: Dict[str, Any] | None = None) -> None:
        entry = LogEntry(
            level=level,
            message=message,
            meta=metadata if metadata is not None else {},
            timestamp=datetime.now(timezone.utc)
        )
        self._session.add(entry)
        self._session.commit()


def log_event(level: str, message: str, metadata: Dict[str, Any] | None = None) -> None:
    db_path = os.environ.get("SCRAPYARD_NETWORK_LOGGER_DB", "network_logger.db")
    engine = create_engine(f"sqlite:///{db_path}")
    IntPKModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            logger = NetworkLogger(session)
            logger.log(level, message, metadata)
    finally:
        engine.dispose()


def _selftest() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_log_event.db")
        os.environ["SCRAPYARD_NETWORK_LOGGER_DB"] = db_path
        
        try:
            log_event("info", "test message via log_event", {"source": "selftest", "id": 1})
            
            engine = create_engine(f"sqlite:///{db_path}")
            try:
                with Session(engine) as session:
                    stmt = select(LogEntry).where(LogEntry.level == "info")
                    result = session.execute(stmt).scalar_one()
                    assert result.message == "test message via log_event"
                    assert result.meta == {"source": "selftest", "id": 1}
                    assert isinstance(result.timestamp, datetime)
            finally:
                engine.dispose()
            
            db_path2 = os.path.join(tmpdir, "test_direct.db")
            engine2 = create_engine(f"sqlite:///{db_path2}")
            IntPKModel.metadata.create_all(engine2)
            try:
                with Session(engine2) as session:
                    logger = NetworkLogger(session)
                    logger.log("error", "direct logger test", {"error_code": 500, "details": {"foo": "bar"}})
                    
                    stmt = select(LogEntry).where(LogEntry.level == "error")
                    result = session.execute(stmt).scalar_one()
                    assert result.message == "direct logger test"
                    assert result.meta["error_code"] == 500
                    assert result.meta["details"]["foo"] == "bar"
            finally:
                engine2.dispose()
                
        finally:
            if "SCRAPYARD_NETWORK_LOGGER_DB" in os.environ:
                del os.environ["SCRAPYARD_NETWORK_LOGGER_DB"]


if __name__ == "__main__":
    _selftest()
