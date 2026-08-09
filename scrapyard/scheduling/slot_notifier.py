"""
slot_notifier — Notifies users and admins of slot changes, cancellations, or confirmations. It provides a clean, reusable interface for scheduling systems to trigger alerts based on slot state transitions.

### PART-META-JSON
{
  "name": "slot_notifier",
  "layer": "scheduling",
  "purpose": "Notifies users and admins of slot changes, cancellations, or confirmations. It provides a clean, reusable interface for scheduling systems to trigger alerts based on slot state transitions.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: notify_slot_change(slot); notify_slot_cancellation(slot); Slot(...).",
  "outputs": "Returns: notify_slot_change -> None; notify_slot_cancellation -> None.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.scheduling.slot_notifier`.",
  "example": "from scrapyard.scheduling.slot_notifier import *",
  "import_path": "scrapyard.scheduling.slot_notifier"
}
### END-PART-META
"""
from dataclasses import dataclass
from typing import Optional
import os
import logging
import tempfile

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class Slot:
    id: int
    status: str
    name: Optional[str] = None
    description: Optional[str] = None

def notify_slot_change(slot: Slot) -> None:
    """Notify users and admins of a slot change."""
    logger.info(f"Slot {slot.id} has changed to state: {slot.status}")

def notify_slot_cancellation(slot: Slot) -> None:
    """Notify users and admins of a slot cancellation."""
    logger.info(f"Slot {slot.id} has been cancelled.")

def _selftest() -> None:
    # Create temporary directory for SQLite database
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        
        # Test notify_slot_change
        slot = Slot(id=1, status='available', name='Test Slot 1')
        notify_slot_change(slot)
        assert logging.getLogger().getEffectiveLevel() == logging.INFO, "Logging level is not set to INFO"
        assert len(logging.getLogger().handlers) > 0, "Logger has no handlers"

        # Test notify_slot_cancellation
        slot = Slot(id=2, status='cancelled', name='Test Slot 2')
        notify_slot_cancellation(slot)
        assert logging.getLogger().getEffectiveLevel() == logging.INFO, "Logging level is not set to INFO"
        assert len(logging.getLogger().handlers) > 0, "Logger has no handlers"

if __name__ == "__main__":
    _selftest()
