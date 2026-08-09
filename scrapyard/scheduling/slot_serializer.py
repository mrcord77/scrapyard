"""
slot_serializer — ** Serializes and deserializes meeting scheduling slot data for API communication, ensuring consistent data representation between internal models and external payloads. This module enables seamless d

### PART-META-JSON
{
  "name": "slot_serializer",
  "layer": "scheduling",
  "purpose": "Serializes and deserializes meeting scheduling slot data for API communication, ensuring consistent data representation between internal models and external payloads. This module enables seamless d.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: serialize_slot(slot); deserialize_slot(data); Slot(...).",
  "outputs": "Returns: serialize_slot -> dict; deserialize_slot -> Slot.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.scheduling.slot_serializer`.",
  "example": "from scrapyard.scheduling.slot_serializer import *",
  "import_path": "scrapyard.scheduling.slot_serializer"
}
### END-PART-META
"""
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, Any
import os, logging, sqlite3, tempfile

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class Slot:
    id: int
    start_time: datetime
    end_time: datetime
    description: str
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

def serialize_slot(slot: Slot) -> dict:
    """Serialize a Slot instance to a dictionary."""
    return {
        'id': slot.id,
        'start_time': slot.start_time.isoformat(),
        'end_time': slot.end_time.isoformat(),
        'description': slot.description,
        'is_active': slot.is_active,
        'metadata': slot.metadata
    }

def deserialize_slot(data: dict) -> Slot:
    """Deserialize a dictionary back to a Slot instance."""
    return Slot(
        id=data['id'],
        start_time=datetime.fromisoformat(data['start_time']),
        end_time=datetime.fromisoformat(data['end_time']),
        description=data.get('description', ''),
        is_active=data.get('is_active', True),
        metadata=data.get('metadata', {})
    )

def _selftest() -> None:
    """Self-test the module for consistency and correctness."""
    logger.info("Starting self-test")

    # Create a temporary SQLite database
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        conn = sqlite3.connect(os.path.join(temp_dir, 'test.db'))
        cursor = conn.cursor()

        # Create a test slot
        test_slot = Slot(
            id=1,
            start_time=datetime(2023, 10, 1, 8, 0, tzinfo=timezone.utc),
            end_time=datetime(2023, 10, 1, 9, 0, tzinfo=timezone.utc),
            description="Test slot",
            is_active=True,
            metadata={"key": "value"}
        )

        # Serialize the test slot
        serialized_data = serialize_slot(test_slot)
        logger.debug(f"Serialized data: {serialized_data}")

        # Deserialize the serialized data back to a Slot instance
        deserialized_slot = deserialize_slot(serialized_data)
        logger.debug(f"Deserialized slot: {deserialized_slot}")

        # Check if the round-trip is consistent
        assert test_slot.id == deserialized_slot.id, "ID mismatch"
        assert test_slot.start_time == deserialized_slot.start_time, "Start time mismatch"
        assert test_slot.end_time == deserialized_slot.end_time, "End time mismatch"
        assert test_slot.description == deserialized_slot.description, "Description mismatch"
        assert test_slot.is_active == deserialized_slot.is_active, "Active status mismatch"
        assert test_slot.metadata == deserialized_slot.metadata, "Metadata mismatch"

    logger.info("Self-test completed successfully")

if __name__ == "__main__":
    _selftest()
