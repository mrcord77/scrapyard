"""
system_information — Retrieve OS metadata (platform module) and CPU usage (psutil when available) behind one small API.

### PART-META-JSON
{
  "name": "system_information",
  "layer": "desktop",
  "purpose": "System metrics for desktop apps: get_os_info() returns platform/OS metadata, get_cpu_usage() returns CPU percent via psutil (0.0 when psutil is absent).",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "None (reads local system state only).",
  "outputs": "get_os_info() dict of platform strings; get_cpu_usage() float 0-100.",
  "files_created": [],
  "security_notes": "Exposes hostname and OS/hardware details - avoid sending get_os_info() output to third parties or logs shared outside the machine without need.",
  "ai_usage": "Import what you need from `scrapyard.desktop.system_information`.",
  "example": "from scrapyard.desktop.system_information import *",
  "import_path": "scrapyard.desktop.system_information"
}
### END-PART-META
"""
import logging
import platform
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)


def get_os_info() -> Dict[str, Any]:
    """
    Retrieve operating system metadata.
    
    Returns:
        Dictionary containing system, release, version, machine, processor,
        platform, and node information.
    """
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "platform": platform.platform(),
        "node": platform.node(),
    }


def get_cpu_usage() -> float:
    """
    Retrieve current CPU usage percentage.
    
    Returns:
        Float between 0.0 and 100.0 representing CPU usage percentage.
        Returns 0.0 if psutil is not available.
    """
    try:
        import psutil
        usage = psutil.cpu_percent(interval=0.1)
        return float(usage)
    except ImportError:
        logger.debug("psutil not available, returning 0.0 for CPU usage")
        return 0.0


def _selftest() -> None:
    """
    Self-test function to validate module functionality.
    
    Tests:
    - get_os_info returns valid OS metadata
    - get_cpu_usage returns float between 0.0 and 100.0
    - No exceptions raised under normal conditions
    - SQLite temporary database operations work correctly
    - Completes in under 20 seconds
    """
    import tempfile
    import sqlite3
    import time
    
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        os_info = get_os_info()
        assert isinstance(os_info, dict), "get_os_info must return a dict"
        assert "system" in os_info, "os_info must contain 'system' key"
        assert "platform" in os_info, "os_info must contain 'platform' key"
        assert isinstance(os_info["system"], str), "system value must be a string"
        
        cpu_usage = get_cpu_usage()
        assert isinstance(cpu_usage, (int, float)), "get_cpu_usage must return a number"
        cpu_float = float(cpu_usage)
        assert 0.0 <= cpu_float <= 100.0, f"CPU usage must be between 0.0 and 100.0, got {cpu_float}"
        
        db_path = os.path.join(tmpdir, "test_system_info.db")
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE test_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    value REAL
                )
            """)
            cursor.execute(
                "INSERT INTO test_metrics (name, value) VALUES (?, ?)",
                ("cpu_usage", cpu_float)
            )
            conn.commit()
            cursor.execute("SELECT name, value FROM test_metrics")
            rows = cursor.fetchall()
            assert len(rows) == 1, "Should have exactly one row in test table"
            assert rows[0][0] == "cpu_usage", "Stored metric name should match"
            assert isinstance(rows[0][1], float), "Stored value should be float"
        finally:
            conn.close()
    
    elapsed = time.time() - start_time
    assert elapsed < 20, f"Selftest took {elapsed:.2f}s, must complete in under 20s"


if __name__ == "__main__":
    _selftest()
