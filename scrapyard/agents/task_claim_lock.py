"""
task_claim_lock — task claim lock

### PART-META-JSON
{
  "name": "task_claim_lock",
  "layer": "agents",
  "purpose": "task claim lock",
  "addition": true,
  "status": "core",
  "dependencies": [
    "task_queue",
    "queen_worker_dispatch"
  ],
  "inputs": "Public API: TaskClaimLock(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.agents.task_claim_lock`.",
  "example": "from scrapyard.agents.task_claim_lock import *",
  "import_path": "scrapyard.agents.task_claim_lock"
}
### END-PART-META
"""

from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class TaskClaimLock:
    task_id: str
    lock_id: str
    _lock_state: bool = False
    
    def is_locked(self) -> bool:
        return self._lock_state
    
    def lock_task(self) -> None:
        if not self.is_locked():
            self._lock_state = True
            logger.info(f"Task {self.task_id} locked by {self.lock_id}")
        else:
            raise RuntimeError(f"Task {self.task_id} is already locked")
    
    def unlock_task(self) -> None:
        if self.is_locked():
            self._lock_state = False
            logger.info(f"Task {self.task_id} unlocked by {self.lock_id}")
        else:
            raise RuntimeError(f"Task {self.task_id} is not currently locked")

def _selftest() -> None:
    # Create a temporary task claim lock instance
    lock1 = TaskClaimLock(task_id="task-001", lock_id="worker-001")
    
    # Test initial state
    assert not lock1.is_locked(), "Task should be unlocked initially"
    
    # Attempt to lock the task
    try:
        lock1.lock_task()
    except RuntimeError as e:
        raise AssertionError(f"Locking failed with unexpected error: {e}")
    
    # Verify that the task is now locked
    assert lock1.is_locked(), "Task should be locked after locking"
    
    # Attempt to lock the same task again
    try:
        lock1.lock_task()
        raise AssertionError("Re-locking a locked task did not raise an error")
    except RuntimeError as e:
        assert str(e) == f"Task {lock1.task_id} is already locked", "Unexpected error message"
    
    # Unlock the task and verify that it works
    try:
        lock1.unlock_task()
    except RuntimeError as e:
        raise AssertionError(f"Unlocking failed with unexpected error: {e}")
    
    assert not lock1.is_locked(), "Task should be unlocked after unlocking"
    
    # Attempt to unlock an already unlocked task
    try:
        lock1.unlock_task()
        raise AssertionError("Un-locking an unlocked task did not raise an error")
    except RuntimeError as e:
        assert str(e) == f"Task {lock1.task_id} is not currently locked", "Unexpected error message"
    
    logger.info("Self-test passed successfully")

if __name__ == "__main__":
    _selftest()
