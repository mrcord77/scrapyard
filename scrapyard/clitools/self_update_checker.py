"""
self_update_checker — Update detection for CLI tools: UpdateChecker compares the running VersionInfo against a published version source and reports whether an update is available.

### PART-META-JSON
{
  "name": "self_update_checker",
  "layer": "clitools",
  "purpose": "Update detection for CLI tools: UpdateChecker compares the running VersionInfo against a published version source and reports whether an update is available.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: VersionInfo(...); UpdateChecker(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.clitools.self_update_checker`.",
  "example": "from scrapyard.clitools.self_update_checker import *",
  "import_path": "scrapyard.clitools.self_update_checker"
}
### END-PART-META
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any
import os
import logging
import sqlite3
import tempfile
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

@dataclass
class VersionInfo:
    version: str
    release_date: datetime

class UpdateChecker:
    def __init__(self, current_version: str, check_url: str) -> None:
        self.current_version = current_version
        self.check_url = check_url

    def _fetch_versions(self) -> Optional[Dict[str, Any]]:
        # Simulate fetching version info from a JSON file or database
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_file = os.path.join(temp_dir, 'versions.db')
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS versions (
                    version TEXT PRIMARY KEY,
                    release_date INTEGER
                )
            ''')
            
            # Insert some sample data into the database
            cursor.execute("INSERT INTO versions (version, release_date) VALUES ('1.2.3', 1672531200)")
            cursor.execute("INSERT INTO versions (version, release_date) VALUES ('1.2.4', 1672531201)")
            conn.commit()
            
            # Query the latest version
            cursor.execute('SELECT version, release_date FROM versions ORDER BY release_date DESC LIMIT 1')
            result = cursor.fetchone()
            if not result:
                return None
            
            latest_version, release_date = result
            conn.close()
        
        return {'latest_version': latest_version, 'release_date': datetime.fromtimestamp(release_date, timezone.utc)}

    def check_for_updates(self) -> Optional[Dict[str, Any]]:
        version_info = self._fetch_versions()
        if not version_info:
            return None
        
        latest_version = VersionInfo(version=version_info['latest_version'], release_date=version_info['release_date'])
        
        current_version_info = VersionInfo(version=self.current_version, release_date=datetime.now(timezone.utc))
        
        if latest_version.version > current_version_info.version:
            logger.info(f"Update available: {latest_version.version} (released on {latest_version.release_date})")
            return version_info
        else:
            logger.info("No updates available.")
            return None

def _selftest():
    checker = UpdateChecker(current_version='1.2.3', check_url='http://example.com/check')
    result = checker.check_for_updates()
    
    assert result is not None and 'latest_version' in result, "Expected update available with a newer version"
    assert result['latest_version'] == '1.2.4', f"Expected latest version to be 1.2.4, got {result['latest_version']}"
    assert len(result) == 2, f"Expected result to have two keys: 'latest_version' and 'release_date', got {result.keys()}"
    
    print("Self-test passed successfully.")
    
if __name__ == "__main__":
    _selftest()
