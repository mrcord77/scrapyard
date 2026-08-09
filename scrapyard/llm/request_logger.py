"""
request_logger — Log detailed information about each LLM inference request for debugging and auditing, ensuring traceability and compliance.

### PART-META-JSON
{
  "name": "request_logger",
  "layer": "llm",
  "purpose": "Log detailed information about each LLM inference request for debugging and auditing, ensuring traceability and compliance.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "llm_request"
  ],
  "inputs": "Public API: generate_log_entry(request_id, payload, response); log_request_details(request_id, payload, response, session); RequestDetails(...); RequestLog(...).",
  "outputs": "Returns: generate_log_entry -> Dict[str, Any]; log_request_details -> None.",
  "files_created": [
    "request_logs"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.llm.request_logger`.",
  "example": "from scrapyard.llm.request_logger import *",
  "import_path": "scrapyard.llm.request_logger"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, JSON, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, Any, Optional
import os
import logging
import tempfile

logger = logging.getLogger(__name__)


@dataclass
class RequestDetails:
    request_id: str
    payload: dict
    response: dict


def generate_log_entry(request_id: str, payload: dict, response: dict) -> Dict[str, Any]:
    """Generate a log entry for the given request details."""
    return {
        "request_id": request_id,
        "payload": payload,
        "response": response,
        "timestamp": datetime.utcnow()
    }


def log_request_details(
    request_id: str,
    payload: dict,
    response: dict,
    session: Optional[Session] = None
) -> None:
    """Log detailed information about each LLM inference request."""
    entry = generate_log_entry(request_id, payload, response)
    
    if session is None:
        raise RuntimeError("Database session not provided")
    
    new_log = RequestLog(**entry)
    session.add(new_log)
    session.flush()
    logger.debug(f"Logged request {request_id}")


class RequestLog(IntPKModel):
    __tablename__ = 'request_logs'
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[JSON] = mapped_column(JSON)
    response: Mapped[JSON] = mapped_column(JSON)
    timestamp: Mapped[DateTime] = mapped_column(DateTime, default=datetime.utcnow)


def _selftest() -> None:
    """Self-test the module to ensure it works as expected."""
    # Create a temporary database
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create tables
        IntPKModel.metadata.create_all(engine)

        # Test log entry creation and retrieval
        request_id = "test_request_id"
        payload = {"input": "hello", "parameters": {}}
        response = {"output": "world"}

        with Session(bind=engine) as session:
            log_request_details(request_id, payload, response, session=session)
            session.commit()
            
            result = session.execute(
                select(RequestLog).where(RequestLog.request_id == request_id)
            ).scalars().first()
            
            assert result is not None, "Log entry was not created"
            assert result.request_id == request_id
            assert result.payload == payload
            assert result.response == response
            assert isinstance(result.timestamp, datetime)

        # Dispose the engine
        engine.dispose()
        
        logger.info("Self-test passed")


if __name__ == "__main__":
    _selftest()
