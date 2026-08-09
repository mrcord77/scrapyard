"""
slot_validator — ** Validates meeting scheduling slots for consistency, detects overlaps, and ensures data integrity without relying on external systems. It serves as a foundational component for ensuring accurate and

### PART-META-JSON
{
  "name": "slot_validator",
  "layer": "scheduling",
  "purpose": "Validates meeting scheduling slots for consistency, detects overlaps, and ensures data integrity without relying on external systems. It serves as a foundational component for ensuring accurate and.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: validate_slot(slot); check_for_overlaps(slot, existing_slots); Slot(...).",
  "outputs": "Returns: validate_slot -> None; check_for_overlaps -> List[Slot].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.scheduling.slot_validator`.",
  "example": "from scrapyard.scheduling.slot_validator import *",
  "import_path": "scrapyard.scheduling.slot_validator"
}
### END-PART-META
"""
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import List
import logging

logger = logging.getLogger(__name__)

@dataclass
class Slot:
    start_time: datetime
    end_time: datetime
    description: str = ""

def validate_slot(slot: Slot) -> None:
    if slot.start_time >= slot.end_time:
        raise ValueError("Invalid time range: start_time must be before end_time")
    if not (slot.start_time.tzinfo and slot.end_time.tzinfo):
        raise ValueError("Time zones must be specified for both start_time and end_time")

def check_for_overlaps(slot: Slot, existing_slots: List[Slot]) -> List[Slot]:
    overlapping_slots = []
    for existing_slot in existing_slots:
        if (slot.start_time <= existing_slot.end_time and slot.end_time >= existing_slot.start_time):
            overlapping_slots.append(existing_slot)
    return overlapping_slots

def _selftest():
    # Test data
    slot1 = Slot(start_time=datetime(2023, 10, 1, 9, 0, tzinfo=timezone(timedelta(hours=-5))),
                 end_time=datetime(2023, 10, 1, 10, 0, tzinfo=timezone(timedelta(hours=-5))),
                 description="Test Slot 1")
    slot2 = Slot(start_time=datetime(2023, 10, 1, 8, 0, tzinfo=timezone(timedelta(hours=-5))),
                 end_time=datetime(2023, 10, 1, 9, 0, tzinfo=timezone(timedelta(hours=-5))),
                 description="Test Slot 2")
    slot3 = Slot(start_time=datetime(2023, 10, 1, 10, 0, tzinfo=timezone(timedelta(hours=-5))),
                 end_time=datetime(2023, 10, 1, 11, 0, tzinfo=timezone(timedelta(hours=-5))),
                 description="Test Slot 3")

    # Validate slot
    try:
        validate_slot(slot1)
        logger.info("Slot validation passed")
    except ValueError as e:
        logger.error(f"Slot validation failed: {e}")

    # Check for overlaps
    existing_slots = [slot2, slot3]
    overlapping_slots = check_for_overlaps(slot1, existing_slots)
    assert len(overlapping_slots) == 2, "Overlap detection failed"
    logger.info("Overlap detection passed")

if __name__ == "__main__":
    _selftest()
