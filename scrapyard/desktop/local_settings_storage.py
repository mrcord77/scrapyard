"""
local_settings_storage — Persist and retrieve desktop application settings as JSON files with defaults and corrupt-file fallback.

### PART-META-JSON
{
  "name": "local_settings_storage",
  "layer": "desktop",
  "purpose": "JSON-file settings persistence: load_settings(path, default) tolerates missing/corrupt files and returns defaults; save_settings creates parent dirs and writes UTF-8 JSON.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "file_path, settings dict, optional defaults dict.",
  "outputs": "Settings dict; JSON file on disk.",
  "files_created": ["<file_path> JSON settings file"],
  "security_notes": "Settings are plaintext JSON on disk - never store credentials/tokens here; use OS credential stores for secrets. Corrupt files are silently replaced by defaults, so keep backups if settings are precious.",
  "ai_usage": "Import what you need from `scrapyard.desktop.local_settings_storage`.",
  "example": "from scrapyard.desktop.local_settings_storage import *",
  "import_path": "scrapyard.desktop.local_settings_storage"
}
### END-PART-META
"""
import json
import logging
import os
import tempfile
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def load_settings(file_path: str, default: Optional[Dict] = None) -> Dict:
    """Load settings from a JSON file.
    
    Args:
        file_path: Path to the JSON settings file.
        default: Default dictionary to return if file does not exist or is invalid.
            If None, returns an empty dict.
            
    Returns:
        Dictionary containing the loaded settings, or the default if loading fails.
    """
    if default is None:
        default = {}
    
    if not os.path.exists(file_path):
        return default.copy()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return default.copy()
            return data
    except (json.JSONDecodeError, IOError):
        return default.copy()


def save_settings(file_path: str, data: Dict) -> None:
    """Save settings to a JSON file.
    
    Args:
        file_path: Path to the JSON settings file.
        data: Dictionary containing settings to save.
    """
    parent_dir = os.path.dirname(file_path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _selftest() -> None:
    """Verify core functionality of local_settings_storage."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Test 1: Missing file returns default
        missing_path = os.path.join(tmpdir, "nonexistent.json")
        default_data = {"default_key": "default_value"}
        result = load_settings(missing_path, default=default_data)
        assert result == default_data, "Failed to return default for missing file"
        
        # Verify default is not mutated
        result["default_key"] = "modified"
        assert default_data["default_key"] == "default_value", "Default was mutated"
        
        # Test 2: Save and load preserves data
        settings_path = os.path.join(tmpdir, "settings.json")
        test_data = {
            "string": "value",
            "integer": 42,
            "float": 3.14,
            "boolean": True,
            "list": [1, 2, 3],
            "nested": {"key": "value"}
        }
        save_settings(settings_path, test_data)
        loaded = load_settings(settings_path)
        assert loaded == test_data, "Data not preserved across save/load"
        
        # Test 3: Missing file without default returns empty dict
        empty_result = load_settings(os.path.join(tmpdir, "no_default.json"))
        assert empty_result == {}, "Should return empty dict when no default provided"
        
        # Test 4: Overwrite existing file
        new_data = {"updated": "data"}
        save_settings(settings_path, new_data)
        reloaded = load_settings(settings_path)
        assert reloaded == new_data, "Failed to overwrite existing file"
        
        # Test 5: Subdirectory creation
        deep_path = os.path.join(tmpdir, "subdir", "deep", "settings.json")
        deep_data = {"deep": "value"}
        save_settings(deep_path, deep_data)
        deep_loaded = load_settings(deep_path)
        assert deep_loaded == deep_data, "Failed to create subdirectories"
        
    logger.info("_selftest passed")


if __name__ == "__main__":
    _selftest()
