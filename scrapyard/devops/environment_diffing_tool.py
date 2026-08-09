"""
environment_diffing_tool — Compare and diff software environments (dev, staging, prod) by analyzing configuration and state differences. Enables rapid identification of drift and misalignment between environments.

### PART-META-JSON
{
  "name": "environment_diffing_tool",
  "layer": "devops",
  "purpose": "Compare and diff software environments (dev, staging, prod) by analyzing configuration and state differences. Enables rapid identification of drift and misalignment between environments.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: diff_environments(left, right); EnvironmentDiff(...).",
  "outputs": "Returns: diff_environments -> EnvironmentDiff.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.devops.environment_diffing_tool`.",
  "example": "from scrapyard.devops.environment_diffing_tool import *",
  "import_path": "scrapyard.devops.environment_diffing_tool"
}
### END-PART-META
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
import logging
import tempfile
import sqlite3
import json

logger = logging.getLogger(__name__)


@dataclass
class EnvironmentDiff:
    differences: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"differences": self.differences}

    def get_summary(self) -> str:
        summary = []
        for diff in self.differences:
            summary.append(f"{diff['path']}: {diff['left']} != {diff['right']}")
        return "\n".join(summary)


def diff_environments(left: Dict[str, Any], right: Dict[str, Any]) -> EnvironmentDiff:
    """
    Compare two environment configurations and return a list of differences.
    """
    differences = []
    _diff(left, right, "", differences)
    return EnvironmentDiff(differences=differences)


def _diff(left: Dict[str, Any], right: Dict[str, Any], path: str, differences: List[Dict[str, Any]]) -> None:
    for key in left.keys() - right.keys():
        new_path = f"{path}/{key}" if path else key
        differences.append({"path": new_path, "left": left[key], "right": None})
    for key in right.keys() - left.keys():
        new_path = f"{path}/{key}" if path else key
        differences.append({"path": new_path, "left": None, "right": right[key]})
    for key in set(left.keys()).intersection(right.keys()):
        new_path = f"{path}/{key}" if path else key
        if isinstance(left[key], dict) and isinstance(right[key], dict):
            _diff(left[key], right[key], new_path, differences)
        elif left[key] != right[key]:
            differences.append({"path": new_path, "left": left[key], "right": right[key]})


def _selftest() -> None:
    """
    Self-test the module to ensure it works as expected.
    """
    logger.info("Starting self-test for environment_diffing_tool")

    # Test case 1: No differences
    env1 = {"a": 1, "b": {"c": 2}}
    env2 = {"a": 1, "b": {"c": 2}}
    diff = diff_environments(env1, env2)
    assert len(diff.differences) == 0, f"Expected no differences, got {diff.differences}"

    # Test case 2: Simple key-value difference
    env1 = {"a": 1}
    env2 = {"a": 2}
    diff = diff_environments(env1, env2)
    assert len(diff.differences) == 1 and diff.differences[0]["path"] == "a" and diff.differences[0]["left"] == 1 and diff.differences[0]["right"] == 2

    # Test case 3: Nested dictionary difference
    env1 = {"a": 1, "b": {"c": 2}}
    env2 = {"a": 1, "b": {"c": 3}}
    diff = diff_environments(env1, env2)
    assert len(diff.differences) == 1 and diff.differences[0]["path"] == "b/c" and diff.differences[0]["left"] == 2 and diff.differences[0]["right"] == 3

    # Test case 4: Complex nested structure
    env1 = {"a": 1, "b": {"c": {"d": 4}}}
    env2 = {"a": 1, "b": {"c": {"d": 5}}}
    diff = diff_environments(env1, env2)
    assert len(diff.differences) == 1 and diff.differences[0]["path"] == "b/c/d" and diff.differences[0]["left"] == 4 and diff.differences[0]["right"] == 5

    # Test case 5: Test to_dict and get_summary methods
    env1 = {"x": 10, "y": {"z": 20}}
    env2 = {"x": 11, "y": {"z": 20}, "w": 30}
    diff = diff_environments(env1, env2)
    
    # Check to_dict
    diff_dict = diff.to_dict()
    assert "differences" in diff_dict
    assert len(diff_dict["differences"]) == 2
    
    # Check get_summary
    summary = diff.get_summary()
    assert "x:" in summary
    assert "w:" in summary
    
    # Test case 6: SQLite integration test with proper cleanup
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = f"{tmpdir}/environments.db"
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS env_configs (name TEXT PRIMARY KEY, config TEXT)")
            
            # Insert dev and prod environments
            dev_env = {"database": {"host": "localhost", "port": 5432}, "debug": True, "version": "1.0.0"}
            prod_env = {"database": {"host": "prod.db.com", "port": 5432}, "debug": False, "version": "1.0.0"}
            
            cursor.execute("INSERT INTO env_configs VALUES (?, ?)", ("dev", json.dumps(dev_env)))
            cursor.execute("INSERT INTO env_configs VALUES (?, ?)", ("prod", json.dumps(prod_env)))
            conn.commit()
            
            # Retrieve and diff
            cursor.execute("SELECT config FROM env_configs WHERE name = 'dev'")
            row = cursor.fetchone()
            assert row is not None
            stored_dev = json.loads(row[0])
            
            cursor.execute("SELECT config FROM env_configs WHERE name = 'prod'")
            row = cursor.fetchone()
            assert row is not None
            stored_prod = json.loads(row[0])
            
            db_diff = diff_environments(stored_dev, stored_prod)
            assert len(db_diff.differences) == 2
            
            # Verify paths
            paths = {d["path"] for d in db_diff.differences}
            assert "database/host" in paths
            assert "debug" in paths
            
        finally:
            conn.close()

    logger.info("Self-test passed successfully")


if __name__ == "__main__":
    _selftest()
