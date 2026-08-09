"""
workspace_walker — Track and classify projects in a workspace, storing metadata in SQLite.

### PART-META-JSON
{
  "name": "workspace_walker",
  "layer": "factory_intel",
  "purpose": "Track and classify projects in a workspace, storing metadata in SQLite.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlite3",
    "os",
    "json",
    "tempfile",
    "logging"
  ],
  "inputs": [
    "workspace paths",
    "project metadata"
  ],
  "outputs": [
    "SQLite database with project inventory"
  ],
  "files_created": [
    ".workspace_inventory.db"
  ],
  "security_notes": "No sensitive data stored; all metadata is user-provided and sanitized.",
  "ai_usage": "None",
  "example": "inventory_to_sqlite(':memory:', 'projects/'); get_project_inventory(':memory:')",
  "import_path": "scrapyard.factory_intel.workspace_walker"
}
### END-PART-META
"""

from typing import Any, Dict, List
import os
import json
import sqlite3
import logging
import tempfile
from pathlib import Path

STATUS = "core"

logger = logging.getLogger(__name__)

def _init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS projects ("
                 "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "path TEXT NOT NULL, "
                 "type TEXT, "
                 "tags TEXT, "
                 "last_modified TEXT, "
                 "size INTEGER, "
                 "description TEXT)")
    conn.commit()
    return conn

def _get_project_info(path: str) -> Dict[str, Any]:
    try:
        path = Path(path).resolve()
        if not path.exists():
            return {"error": "Path does not exist"}
        stat = path.stat()
        return {
            "path": str(path),
            "type": "directory" if path.is_dir() else "file",
            "size": stat.st_size,
            "last_modified": stat.st_mtime,
        }
    except Exception as e:
        logger.error(f"Error getting project info for {path}: {e}")
        return {"error": str(e)}

def walk_workspace(db_path: str = ":memory:") -> None:
    """Populate the database with all projects in the current workspace."""
    conn = _init_db(db_path)
    try:
        for root, dirs, files in os.walk("."):
            for dir in dirs:
                dir_path = os.path.join(root, dir)
                info = _get_project_info(dir_path)
                if "error" in info:
                    continue
                info["tags"] = "[]"
                info["description"] = "No description"
                conn.execute("INSERT INTO projects (path, type, size, last_modified) VALUES (?, ?, ?, ?)",
                             (info["path"], info["type"], info["size"], info["last_modified"]))
            for file in files:
                file_path = os.path.join(root, file)
                info = _get_project_info(file_path)
                if "error" in info:
                    continue
                conn.execute("INSERT INTO projects (path, type, size, last_modified) VALUES (?, ?, ?, ?)",
                             (info["path"], info["type"], info["size"], info["last_modified"]))
        conn.commit()
    except Exception as e:
        logger.error(f"Error walking workspace: {e}")
    finally:
        conn.close()

def classify_project(path: str) -> Dict[str, Any]:
    """Classify a project by path, returning metadata."""
    info = _get_project_info(path)
    if "error" in info:
        return {"error": info["error"]}
    try:
        # Simulated classification logic
        if path.endswith(".py"):
            info["type"] = "python_script"
        elif os.path.isdir(path):
            info["type"] = "directory"
        elif path.endswith(".md"):
            info["type"] = "markdown"
        else:
            info["type"] = "unknown"
        return info
    except Exception as e:
        logger.error(f"Error classifying project {path}: {e}")
        return {"error": str(e)}

def inventory_to_sqlite(db_path: str, root: str = "factory/") -> None:
    """Populate SQLite with project inventory from the given root directory."""
    conn = _init_db(db_path)
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            for dir in dirnames:
                dir_path = os.path.join(dirpath, dir)
                info = _get_project_info(dir_path)
                if "error" in info:
                    continue
                info["tags"] = "[]"
                info["description"] = "No description"
                conn.execute("INSERT INTO projects (path, type, size, last_modified) VALUES (?, ?, ?, ?)",
                             (info["path"], info["type"], info["size"], info["last_modified"]))
            for file in filenames:
                file_path = os.path.join(dirpath, file)
                info = _get_project_info(file_path)
                if "error" in info:
                    continue
                conn.execute("INSERT INTO projects (path, type, size, last_modified) VALUES (?, ?, ?, ?)",
                             (info["path"], info["type"], info["size"], info["last_modified"]))
        conn.commit()
    except Exception as e:
        logger.error(f"Error populating inventory: {e}")
    finally:
        conn.close()

def get_project_inventory(db_path: str) -> List[Dict[str, Any]]:
    """Retrieve all project inventory from the database."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects")
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        inventory = [dict(zip(columns, row)) for row in rows]
        return inventory
    except Exception as e:
        logger.error(f"Error retrieving inventory: {e}")
        return []
    finally:
        conn.close()

def _selftest() -> None:
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        db_path = tmp.name
    try:
        inventory_to_sqlite(db_path, root=".")
        inventory = get_project_inventory(db_path)
        assert len(inventory) > 0, "No projects found in inventory"
        for item in inventory:
            assert "path" in item, "Missing 'path' field"
            assert "type" in item, "Missing 'type' field"
            assert "size" in item, "Missing 'size' field"
            assert "last_modified" in item, "Missing 'last_modified' field"
    except Exception as e:
        logger.error(f"Selftest failed: {e}")
        raise AssertionError(f"Selftest failed: {e}") from e
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


if __name__ == "__main__":
    _selftest()
