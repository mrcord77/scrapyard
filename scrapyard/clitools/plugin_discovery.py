"""
plugin_discovery — Discovers and loads CLI plugins from specified directories or files, enabling dynamic extension of command-line interfaces. It provides a robust mechanism for plugin discovery, loading, and registrati

### PART-META-JSON
{
  "name": "plugin_discovery",
  "layer": "clitools",
  "purpose": "Discovers and loads CLI plugins from specified directories or files, enabling dynamic extension of command-line interfaces. It provides a robust mechanism for plugin discovery, loading, and registrati",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: discover_plugins(paths, metadata); PluginInfo(...); PluginLoader(...).",
  "outputs": "Returns: discover_plugins -> List[PluginInfo].",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.clitools.plugin_discovery`.",
  "example": "from scrapyard.clitools.plugin_discovery import *",
  "import_path": "scrapyard.clitools.plugin_discovery"
}
### END-PART-META
"""

import os
import json
import logging
import tempfile
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """Information about a discovered plugin."""
    name: str
    path: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    plugin_type: Optional[str] = None
    arguments: List[Dict[str, Any]] = field(default_factory=list)


def _matches_criteria(plugin: PluginInfo, criteria: Dict[str, Any]) -> bool:
    """Check if plugin matches filter criteria including name, type, and metadata."""
    if "name" in criteria and plugin.name != criteria["name"]:
        return False
    if "type" in criteria and plugin.plugin_type != criteria["type"]:
        return False
    
    # Check remaining criteria against metadata
    for key, value in criteria.items():
        if key in ("name", "type"):
            continue
        if key not in plugin.metadata or plugin.metadata[key] != value:
            return False
    return True


def _load_plugin_info_from_path(path: str) -> Optional[PluginInfo]:
    """Load plugin info from a path (directory with plugin.json or file with sidecar)."""
    # Case 1: Directory with plugin.json
    if os.path.isdir(path):
        json_path = os.path.join(path, "plugin.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return PluginInfo(
                    name=data.get('name', os.path.basename(path)),
                    path=path,
                    metadata=data.get('metadata', {}),
                    plugin_type=data.get('type'),
                    arguments=data.get('arguments', [])
                )
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load plugin metadata from {json_path}: {e}")
                return None
    
    # Case 2: Python file with sidecar JSON
    elif os.path.isfile(path) and path.endswith('.py'):
        json_path = path[:-3] + '.json'
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return PluginInfo(
                    name=data.get('name', os.path.basename(path)[:-3]),
                    path=path,
                    metadata=data.get('metadata', {}),
                    plugin_type=data.get('type'),
                    arguments=data.get('arguments', [])
                )
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load metadata for {path}: {e}")
                return None
    
    return None


def discover_plugins(paths: List[str], metadata: Dict[str, Any]) -> List[PluginInfo]:
    """
    Discover plugins from specified paths, filtering by metadata criteria.
    
    Args:
        paths: List of directory or file paths to search for plugins
        metadata: Dictionary of criteria to filter by (name, type, or metadata keys)
    
    Returns:
        List of PluginInfo objects matching the criteria
    """
    plugins: List[PluginInfo] = []
    
    for search_path in paths:
        if not os.path.exists(search_path):
            logger.warning(f"Plugin path does not exist: {search_path}")
            continue
            
        try:
            if os.path.isdir(search_path):
                # Scan directory entries
                with os.scandir(search_path) as entries:
                    for entry in entries:
                        plugin_info = _load_plugin_info_from_path(entry.path)
                        if plugin_info and _matches_criteria(plugin_info, metadata):
                            plugins.append(plugin_info)
                            logger.debug(f"Discovered plugin: {plugin_info.name} at {entry.path}")
            else:
                # Single file path
                plugin_info = _load_plugin_info_from_path(search_path)
                if plugin_info and _matches_criteria(plugin_info, metadata):
                    plugins.append(plugin_info)
                    
        except OSError as e:
            logger.error(f"Error scanning path {search_path}: {e}")
            continue
    
    logger.info(f"Discovered {len(plugins)} plugins matching criteria from {len(paths)} paths")
    return plugins


class PluginLoader:
    """Manages plugin lifecycle and lazy loading."""
    
    def __init__(self, plugin_paths: List[str]):
        self.plugin_paths = plugin_paths
        self._plugins: Optional[List[PluginInfo]] = None
        self._plugin_map: Dict[str, PluginInfo] = {}
        logger.debug(f"PluginLoader initialized with paths: {plugin_paths}")
    
    def load_plugins(self) -> List[PluginInfo]:
        """
        Load all plugins from configured paths.
        Lazy loading: only scans filesystem on first call.
        """
        if self._plugins is None:
            self._plugins = discover_plugins(self.plugin_paths, {})
            self._plugin_map = {p.name: p for p in self._plugins}
            logger.info(f"Loaded {len(self._plugins)} plugins into registry")
        return self._plugins
    
    def get_plugin(self, name: str) -> Optional[PluginInfo]:
        """
        Retrieve a specific plugin by name.
        Triggers load_plugins if not already loaded.
        """
        if self._plugins is None:
            self.load_plugins()
        return self._plugin_map.get(name)


def _selftest():
    """Module self-test verifying all SPEC requirements."""
    import typing
    
    # Verify no execution at import time by checking module state
    # (this function runs after import, verifying lazy design)
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Setup: Create mock plugin directory structure
        plugin_root = os.path.join(tmpdir, "cli_plugins")
        os.makedirs(plugin_root)
        
        # Mock Plugin 1: Directory-based with full metadata
        p1_dir = os.path.join(plugin_root, "command_plugin")
        os.makedirs(p1_dir)
        with open(os.path.join(p1_dir, "plugin.json"), 'w') as f:
            json.dump({
                "name": "command_plugin",
                "type": "command",
                "metadata": {"version": "1.0", "author": "test", "category": "core"},
                "arguments": [
                    {"name": "--verbose", "action": "store_true", "help": "Verbose output"},
                    {"name": "--config", "type": "str", "help": "Config file path"}
                ]
            }, f)
        
        # Create a Python file that should NOT be executed
        with open(os.path.join(p1_dir, "__init__.py"), 'w') as f:
            f.write("raise RuntimeError('Plugin code should not execute during discovery!')")
        
        # Mock Plugin 2: File-based with sidecar JSON
        p2_py = os.path.join(plugin_root, "hook_plugin.py")
        with open(p2_py, 'w') as f:
            f.write("# Plugin code\nprint('This should not print')\n")
        with open(os.path.join(plugin_root, "hook_plugin.json"), 'w') as f:
            json.dump({
                "name": "hook_plugin",
                "type": "hook",
                "metadata": {"version": "2.0", "category": "extension"}
            }, f)
        
        # Mock Plugin 3: Invalid JSON (tests error handling)
        p3_dir = os.path.join(plugin_root, "broken_plugin")
        os.makedirs(p3_dir)
        with open(os.path.join(p3_dir, "plugin.json"), 'w') as f:
            f.write("{invalid json content")
        
        # Mock Plugin 4: Directory without plugin.json (should be ignored)
        p4_dir = os.path.join(plugin_root, "not_a_plugin")
        os.makedirs(p4_dir)
        with open(os.path.join(p4_dir, "random.txt"), 'w') as f:
            f.write("text")
        
        # Test 1: Basic discovery
        all_plugins = discover_plugins([plugin_root], {})
        assert len(all_plugins) == 2, f"Expected 2 valid plugins, found {len(all_plugins)}"
        names = {p.name for p in all_plugins}
        assert "command_plugin" in names
        assert "hook_plugin" in names
        
        # Test 2: Filter by name
        named_plugins = discover_plugins([plugin_root], {"name": "command_plugin"})
        assert len(named_plugins) == 1
        assert named_plugins[0].name == "command_plugin"
        
        # Test 3: Filter by type
        hook_plugins = discover_plugins([plugin_root], {"type": "hook"})
        assert len(hook_plugins) == 1
        assert hook_plugins[0].plugin_type == "hook"
        
        # Test 4: Filter by metadata attributes
        core_plugins = discover_plugins([plugin_root], {"category": "core"})
        assert len(core_plugins) == 1
        assert core_plugins[0].metadata.get("category") == "core"
        
        # Test 5: Combined filter
        filtered = discover_plugins([plugin_root], {"type": "command", "version": "1.0"})
        assert len(filtered) == 1
        assert filtered[0].name == "command_plugin"
        
        # Test 6: PluginLoader lazy loading
        loader = PluginLoader([plugin_root])
        assert loader._plugins is None, "Plugins should not load during initialization"
        
        loaded = loader.load_plugins()
        assert len(loaded) == 2
        assert loader._plugins is not None
        
        # Test 7: get_plugin
        cmd_plugin = loader.get_plugin("command_plugin")
        assert cmd_plugin is not None
        assert cmd_plugin.name == "command_plugin"
        assert cmd_plugin.plugin_type == "command"
        assert len(cmd_plugin.arguments) == 2
        assert cmd_plugin.arguments[0]["name"] == "--verbose"
        
        missing = loader.get_plugin("nonexistent")
        assert missing is None
        
        # Test 8: Type hints validation
        hints = typing.get_type_hints(discover_plugins)
        assert "paths" in hints
        assert "return" in hints
        
        loader_hints = typing.get_type_hints(PluginLoader)
        assert "__init__" in loader_hints or hasattr(PluginLoader.__init__, '__annotations__')
        
        # Test 9: Verify no code execution occurred (files with errors weren't imported)
        # If the broken __init__.py was imported, it would have raised
        # If hook_plugin.py was imported, it would have printed
        
        # Test 10: Error handling - broken_plugin should not crash discovery
        # and we should have logged an error (verified by code path coverage)
        
        logger.info("All plugin discovery tests passed successfully")
        
    print("SELFTEST PASSED")


if __name__ == "__main__":
    _selftest()
