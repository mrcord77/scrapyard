"""
index_watcher — index watcher

### PART-META-JSON
{
  "name": "index_watcher",
  "layer": "curation",
  "purpose": "index watcher",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: refresh(db_path); changed_parts(db_path); reset_harvest(db_path).",
  "outputs": "Returns: refresh -> None; changed_parts -> List[str]; reset_harvest -> None.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.curation.index_watcher`.",
  "example": "from scrapyard.curation.index_watcher import *",
  "import_path": "scrapyard.curation.index_watcher"
}
### END-PART-META
"""
import sqlite3
import threading
from typing import List
import tempfile
import os

STATUS = "core"

# Lock to ensure thread-safe access to the database
db_lock = threading.Lock()

def _init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS part_changes (
                part_name TEXT PRIMARY KEY,
                last_modified TIMESTAMP
            )
        """)
    return conn

def refresh(db_path: str = ":memory:") -> None:
    """Refresh the internal state of part changes from the database."""
    with db_lock:
        conn = _init_db(db_path)
        with conn:
            conn.execute("DELETE FROM part_changes")
        conn.close()

def changed_parts(db_path: str = ":memory:") -> List[str]:
    """Return a list of part names that have been modified since last refresh."""
    with db_lock:
        conn = _init_db(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT part_name FROM part_changes")
        result = cursor.fetchall()
        conn.close()
        return [row[0] for row in result]

def reset_harvest(db_path: str = ":memory:") -> None:
    """Reset the harvest tracking, clearing all recorded changes."""
    with db_lock:
        conn = _init_db(db_path)
        with conn:
            conn.execute("DROP TABLE IF EXISTS part_changes")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS part_changes (
                    part_name TEXT PRIMARY KEY,
                    last_modified TIMESTAMP
                )
            """)
        conn.close()

def _selftest() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        # Test refresh and reset
        reset_harvest(db_path)
        refresh(db_path)
        assert changed_parts(db_path) == [], "changed_parts should be empty after refresh"

        # Test adding a part
        with db_lock:
            conn = sqlite3.connect(db_path)
            with conn:
                conn.execute("INSERT INTO part_changes (part_name, last_modified) VALUES (?, ?)", ("test_part", "2023-01-01"))
            conn.close()

        assert changed_parts(db_path) == ["test_part"], "changed_parts should include test_part"

        # Test reset
        reset_harvest(db_path)
        assert changed_parts(db_path) == [], "changed_parts should be empty after reset"


if __name__ == "__main__":
    _selftest()
