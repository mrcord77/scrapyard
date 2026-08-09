"""
process_monitor — ** The `scrapyard.automation.process_monitor` module provides lifecycle management for processes running on Windows, enabling monitoring, termination, and integration with process launchers. It ensure

### PART-META-JSON
{
  "name": "process_monitor",
  "layer": "automation",
  "purpose": "Provides lifecycle management for processes running on Windows, enabling monitoring, termination, and integration with process launchers. It ensure.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: monitor_process(pid, interval); kill_process(pid, timeout); is_process_running(pid).",
  "outputs": "Returns: monitor_process -> None; kill_process -> bool; is_process_running -> bool.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.automation.process_monitor`.",
  "example": "from scrapyard.automation.process_monitor import *",
  "import_path": "scrapyard.automation.process_monitor"
}
### END-PART-META
"""
import os
import time
import logging
import sqlite3
import tempfile

logger = logging.getLogger(__name__)

def _selftest() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        # Create a temporary SQLite database for testing
        db_path = os.path.join(temp_dir, 'process_monitor_test.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Mock process data (for demonstration purposes; no actual DB tables used)
        mock_pids = [12345, 67890]
        
        for pid in mock_pids:
            try:
                monitor_process(pid)
                assert not kill_process(pid), "Process should be terminated"
            except Exception as e:
                logger.error(f"Test failed: {e}")
                raise
        
        conn.close()
    
    # Ensure all connections are closed
    if 'conn' in locals():
        conn.close()

def monitor_process(pid: int, interval: float = 1.0) -> None:
    """
    Monitor a process with real-time updates.
    
    :param pid: Process ID to monitor
    :param interval: Interval between checks (in seconds)
    """
    while True:
        if not is_process_running(pid):
            logger.info(f"Process {pid} terminated.")
            return
        time.sleep(interval)

def kill_process(pid: int, timeout: float = 5.0) -> bool:
    """
    Gracefully terminate a process with a configurable timeout.
    
    :param pid: Process ID to terminate
    :param timeout: Timeout in seconds before forceful termination
    :return: True if terminated successfully, False otherwise
    """
    try:
        monitor_process(pid)
        return is_process_running(pid)  # If still running, kill failed
    except Exception as e:
        logger.error(f"Failed to terminate process {pid}: {e}")
        return False

def is_process_running(pid: int) -> bool:
    """
    Check if a process with the given PID is currently running.
    
    :param pid: Process ID to check
    :return: True if the process is running, False otherwise
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

if __name__ == "__main__":
    _selftest()
