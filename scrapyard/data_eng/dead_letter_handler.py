"""
dead_letter_handler — Handle and manage failed or invalid data entries that cannot be processed. This module ensures robust error recovery in data pipelines by isolating problematic records for later inspection or reproces

### PART-META-JSON
{
  "name": "dead_letter_handler",
  "layer": "data_eng",
  "purpose": "Handle and manage failed or invalid data entries that cannot be processed. This module ensures robust error recovery in data pipelines by isolating problematic records for later inspection or reproces",
  "addition": true,
  "status": "core",
  "dependencies": [
    "loader"
  ],
  "inputs": "Public API: move_to_dead_letter_queue(record, error); handle_dead_letters(policy); DeadLetterTable(...).",
  "outputs": "Returns: move_to_dead_letter_queue -> None; handle_dead_letters -> List[Dict].",
  "files_created": [
    "dead_letter_table"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.data_eng.dead_letter_handler`.",
  "example": "from scrapyard.data_eng.dead_letter_handler import *",
  "import_path": "scrapyard.data_eng.dead_letter_handler"
}
### END-PART-META
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, JSON, Text, create_engine, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

try:
    from scrapyard.data_eng import loader
except ImportError:
    loader = None  # type: ignore

logger = logging.getLogger(__name__)

# Module-level engine storage (set via _engine global for selftest or external config)
_engine: Optional[Any] = None


class DeadLetterTable(IntPKModel):
    """ORM model for the dead_letter_table.
    
    Stores failed records with error context and processing status.
    """
    __tablename__ = "dead_letter_table"
    
    record_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    error_details: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    processed: Mapped[bool] = mapped_column(Boolean, default=False)


def _get_engine() -> Any:
    """Retrieve the configured database engine."""
    if _engine is None:
        raise RuntimeError(
            "dead_letter_handler module not configured with a database engine. "
            "Set scrapyard.data_eng.dead_letter_handler._engine before use."
        )
    return _engine


def _serialize_record(record: Any) -> dict:
    """Serialize a record to a JSON-compatible dictionary."""
    try:
        if isinstance(record, dict):
            payload = record
        elif hasattr(record, "model_dump") and callable(getattr(record, "model_dump")):
            # Pydantic v2
            payload = record.model_dump()
        elif hasattr(record, "dict") and callable(getattr(record, "dict")):
            # Pydantic v1
            payload = record.dict()
        elif hasattr(record, "__dataclass_fields__"):
            # Dataclass
            payload = {f: getattr(record, f) for f in record.__dataclass_fields__}
        else:
            # Fallback: try to use __dict__ or repr
            if hasattr(record, "__dict__"):
                payload = record.__dict__
            else:
                payload = {"_serialized": str(record)}
        
        # Validate JSON serializability (SQLAlchemy JSON column requirement)
        json.dumps(payload, default=str)
        return payload
    except Exception as exc:
        logger.error(f"Record serialization failed: {exc}")
        return {
            "_serialization_error": str(exc),
            "_repr": repr(record),
            "_type": type(record).__name__
        }


def move_to_dead_letter_queue(record: Any, error: str) -> None:
    """Move a failed record to the dead letter queue for later inspection.
    
    Args:
        record: The failed record (any type, will be serialized to JSON).
        error: Error message or description of why processing failed.
    """
    engine = _get_engine()
    payload = _serialize_record(record)
    
    dead_letter = DeadLetterTable(
        record_payload=payload,
        error_details=error,
        processed=False
    )
    
    with Session(engine) as session:
        session.add(dead_letter)
        session.commit()
        error_preview = f"{error[:50]}..." if len(error) > 50 else error
        logger.info(
            f"Dead letter created: id={dead_letter.id}, "
            f"error='{error_preview}'"
        )


def handle_dead_letters(policy: str = "log") -> List[Dict]:
    """Retrieve and process dead letter records.
    
    Args:
        policy: Processing policy:
            - "log": Log details and mark as processed (default).
            - "delete": Remove records from the table.
            - "reprocess": Return records without marking as processed.
    
    Returns:
        List of dead letter dictionaries with keys: id, record, error, created_at.
    """
    engine = _get_engine()
    results: List[Dict] = []
    
    with Session(engine) as session:
        stmt = select(DeadLetterTable).where(DeadLetterTable.processed == False)
        dead_letters = session.scalars(stmt).all()
        
        for dl in dead_letters:
            entry = {
                "id": dl.id,
                "record": dl.record_payload,
                "error": dl.error_details,
                "created_at": dl.created_at.isoformat() if dl.created_at else None
            }
            results.append(entry)
            
            if policy == "log":
                logger.warning(
                    f"DeadLetter {dl.id} | Error: {dl.error_details} | "
                    f"Record: {json.dumps(dl.record_payload, default=str)[:200]}"
                )
                dl.processed = True
            elif policy == "delete":
                session.delete(dl)
            elif policy == "reprocess":
                # Leave unprocessed for actual reprocessing logic elsewhere
                logger.info(f"DeadLetter {dl.id} queued for reprocessing")
            else:
                logger.warning(f"Unknown policy '{policy}', treating as 'log'")
                dl.processed = True
        
        session.commit()
    
    logger.info(f"Processed {len(results)} dead letters with policy='{policy}'")
    return results


def _selftest() -> None:
    """Offline self-test using temporary SQLite database.
    
    Verifies:
    - Records can be moved to dead letter queue.
    - Records can be retrieved and processed.
    - Database connections are properly managed.
    """
    global _engine
    
    original_engine = _engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_dead_letter.db")
        test_engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            _engine = test_engine
            IntPKModel.metadata.create_all(test_engine)
            
            # Test 1: Basic move and retrieve
            test_data = {"order_id": 99999, "items": ["widget", "gadget"], "total": 150.00}
            test_error_msg = "Payment processing timeout after 30s"
            
            move_to_dead_letter_queue(test_data, test_error_msg)
            
            with Session(test_engine) as session:
                count = session.scalar(select(func.count()).select_from(DeadLetterTable))
                assert count == 1, f"Expected 1 record in table, found {count}"
            
            # Test 2: Handle with log policy (default)
            processed = handle_dead_letters(policy="log")
            assert len(processed) == 1, f"Expected 1 dead letter returned, got {len(processed)}"
            assert processed[0]["error"] == test_error_msg
            assert processed[0]["record"] == test_data
            assert isinstance(processed[0]["id"], int)
            assert processed[0]["created_at"] is not None
            
            # Verify marked as processed
            with Session(test_engine) as session:
                dl = session.scalar(select(DeadLetterTable))
                assert dl.processed is True
            
            # Test 3: Add multiple and test delete policy
            move_to_dead_letter_queue({"batch": 1}, "Error A")
            move_to_dead_letter_queue({"batch": 2}, "Error B")
            
            with Session(test_engine) as session:
                count = session.scalar(select(func.count()).select_from(DeadLetterTable))
                assert count == 3  # 1 processed + 2 new
            
            deleted = handle_dead_letters(policy="delete")
            assert len(deleted) == 2
            assert deleted[0]["record"] == {"batch": 1}
            assert deleted[1]["record"] == {"batch": 2}
            
            with Session(test_engine) as session:
                count = session.scalar(select(func.count()).select_from(DeadLetterTable))
                assert count == 1, f"Expected 1 record remaining after delete, found {count}"
            
            # Test 4: Reprocess policy (should not mark as processed)
            move_to_dead_letter_queue({"retry": True}, "Transient failure")
            reprocess_list = handle_dead_letters(policy="reprocess")
            assert len(reprocess_list) == 1
            assert reprocess_list[0]["record"]["retry"] is True
            
            with Session(test_engine) as session:
                dl = session.get(DeadLetterTable, reprocess_list[0]["id"])
                assert dl.processed is False
            
            # Clean up remaining records before Test 5
            with Session(test_engine) as session:
                for dl in session.scalars(select(DeadLetterTable)).all():
                    session.delete(dl)
                session.commit()
            
            # Test 5: Complex object serialization (simulating dataclass)
            class FakeEvent:
                def __init__(self):
                    self.event_type = "user_action"
                    self.timestamp = "2024-01-15T10:30:00Z"
                    self.user_id = 12345
            
            fake_event = FakeEvent()
            move_to_dead_letter_queue(fake_event, "Complex object test")
            events = handle_dead_letters(policy="log")
            assert len(events) == 1, f"Expected 1 event, got {len(events)}"
            assert events[0]["record"]["event_type"] == "user_action"
            assert events[0]["record"]["user_id"] == 12345
            
            logger.info("All dead_letter_handler self-tests passed")
            
        finally:
            _engine = original_engine


if __name__ == "__main__":
    _selftest()
