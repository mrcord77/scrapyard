"""
config_file_loader — config file loader

### PART-META-JSON
{
  "name": "config_file_loader",
  "layer": "clitools",
  "purpose": "Load YAML/JSON/INI config files into flattened dot-notation dicts with typed env-var overrides and a ConfigManager singleton.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "file_path (.yaml/.yml/.json/.ini), env_prefix, defaults dict.",
  "outputs": "Flattened config dict (dot-notation keys); ConfigManager get/set/to_dict.",
  "files_created": [],
  "security_notes": "Uses yaml.safe_load (never full load) and configparser; no code execution from config. Env overrides can inject values - do not point env_prefix at untrusted environments. Config values may contain secrets: never log the loaded dict wholesale.",
  "ai_usage": "Import what you need from `scrapyard.clitools.config_file_loader`.",
  "example": "from scrapyard.clitools.config_file_loader import *",
  "import_path": "scrapyard.clitools.config_file_loader"
}
### END-PART-META
"""
import configparser
import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


def _flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
    """Flatten a nested dictionary into dot-notation keys."""
    items: list = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def _coerce_ini_value(value: str) -> Any:
    """Best-effort typing for INI string values (int, float, bool, else str)."""
    lowered = value.strip().lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _load_ini(file) -> Dict[str, Any]:
    """Parse an INI file into a nested {section: {key: value}} dict.

    Keys in the [DEFAULT] section land at the top level; values are coerced to
    int/float/bool where they parse cleanly.
    """
    parser = configparser.ConfigParser()
    parser.read_file(file)
    data: Dict[str, Any] = {}
    for key, value in parser.defaults().items():
        data[key] = _coerce_ini_value(value)
    for section in parser.sections():
        section_data: Dict[str, Any] = {}
        for key, value in parser.items(section):
            if key in parser.defaults():
                continue  # inherited DEFAULT keys already at top level
            section_data[key] = _coerce_ini_value(value)
        data[section] = section_data
    return data


def _override_value(config_value: Any, env_value: str) -> Any:
    """
    Override a configuration value with an environment variable value.
    Preserves the type of the original config value if possible.
    """
    if isinstance(config_value, bool):
        return env_value.lower() in ('true', '1', 'yes', 'on')
    elif isinstance(config_value, int):
        return int(env_value)
    elif isinstance(config_value, float):
        return float(env_value)
    else:
        return env_value


def load_config(file_path: str, env_prefix: str = 'APP_', defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Load configuration from a YAML, JSON, or INI file with support for environment variable overrides.
    
    :param file_path: Path to the config file
    :param env_prefix: Prefix for environment variables (default: 'APP_')
    :param defaults: Default configuration values to use if file is missing or as base
    :return: Dictionary of loaded configurations (flattened)
    """
    supported_formats = ['.yaml', '.yml', '.json', '.ini']
    if not any(file_path.endswith(fmt) for fmt in supported_formats):
        raise ValueError(f"Unsupported config file format: {file_path}")
    
    # Start with defaults
    config_data = defaults.copy() if defaults else {}
    
    # Load from file if it exists
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            if file_path.endswith('.json'):
                loaded_data = json.load(file)
            elif file_path.endswith(('.yaml', '.yml')):
                if yaml is None:
                    raise ImportError("PyYAML is required to load YAML files")
                loaded_data = yaml.safe_load(file)
            elif file_path.endswith('.ini'):
                loaded_data = _load_ini(file)
            else:
                loaded_data = {}
        
        # Flatten and merge loaded data (takes precedence over defaults)
        flat_data = _flatten_dict(loaded_data)
        config_data.update(flat_data)
    else:
        logger.warning(f"Config file {file_path} not found, using defaults")
    
    # Apply environment variable overrides
    for key, value in os.environ.items():
        if key.startswith(env_prefix):
            # Convert APP_DATABASE_HOST to database.host
            config_key = key[len(env_prefix):].lower().replace('_', '.')
            if config_key in config_data:
                config_data[config_key] = _override_value(config_data[config_key], value)
            else:
                # Add env var even if not in config file
                config_data[config_key] = value
    
    return config_data


class ConfigManager:
    _instance = None
    config_data: Dict[str, Any] = {}

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize or reinitialize the singleton with new configuration."""
        self.config_data = dict(config)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.
        
        :param key: Configuration key (supports dot notation if keys were flattened)
        :param default: Default value if key is not found
        :return: Value of the configuration key or default
        """
        return self.config_data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Set a configuration value.
        
        :param key: Configuration key
        :param value: New value for the configuration key
        """
        self.config_data[key] = value

    def to_dict(self) -> Dict[str, Any]:
        """
        Get all configuration data as a dictionary.
        
        :return: Dictionary of all configuration keys and values
        """
        return self.config_data.copy()


def _selftest():
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Test 1: Create a YAML config file and load it
        config_path = os.path.join(tmpdir, 'config.yaml')
        with open(config_path, 'w') as f:
            f.write("database:\n  host: localhost\n")
        
        config_data = load_config(config_path, env_prefix='APP_')
        assert config_data['database.host'] == 'localhost', "Failed to load database host from YAML"
        
        # Test 2: Validate ConfigManager getters and setters
        manager = ConfigManager(config_data)
        assert manager.get('database.host') == 'localhost'
        manager.set('database.host', 'newhost')
        assert manager.get('database.host') == 'newhost'
        
        # Test 3: Handle missing config files with fallback defaults
        nonexistent_path = os.path.join(tmpdir, 'nonexistent.yaml')
        config_data_fallback = load_config(nonexistent_path, env_prefix='APP_', defaults={'database.host': 'default_host'})
        assert config_data_fallback['database.host'] == 'default_host', "Failed to use fallback default"
        
        # Test 4: Ensure environment variable precedence over config file values
        os.environ['APP_DATABASE_HOST'] = 'envhost'
        try:
            config_data_env = load_config(config_path, env_prefix='APP_')
            assert config_data_env['database.host'] == 'envhost', "Failed to use environment variable"
        finally:
            del os.environ['APP_DATABASE_HOST']
        
        # Test 5: Test nested config structure loading and access (flattened)
        nested_config_path = os.path.join(tmpdir, 'nestedconfig.yaml')
        with open(nested_config_path, 'w') as f:
            f.write("nested:\n  database:\n    port: 1234\n")
        nested_config_data = load_config(nested_config_path, env_prefix='APP_')
        assert nested_config_data['nested.database.port'] == 1234, "Failed to load nested configuration"
        
        # Test 6: Verify ConfigManager singleton behavior and to_dict
        manager2 = ConfigManager({'test.key': 'value'})
        assert manager.get('test.key') == 'value'  # Should be same instance
        assert manager.to_dict() == {'test.key': 'value'}
        
        # Test 7: JSON support
        json_path = os.path.join(tmpdir, 'config.json')
        with open(json_path, 'w') as f:
            json.dump({'app': {'name': 'testapp'}}, f)
        json_config = load_config(json_path, env_prefix='APP_')
        assert json_config['app.name'] == 'testapp'

        # Test 8: INI support (sections flatten to dot keys, values typed)
        ini_path = os.path.join(tmpdir, 'config.ini')
        with open(ini_path, 'w') as f:
            f.write("[DEFAULT]\nverbose = true\n\n"
                    "[database]\nhost = localhost\nport = 5432\ntimeout = 2.5\n"
                    "enabled = yes\n\n[app]\nname = ini-app\n")
        ini_config = load_config(ini_path, env_prefix='APP_')
        assert ini_config['verbose'] is True, "INI DEFAULT bool not coerced"
        assert ini_config['database.host'] == 'localhost'
        assert ini_config['database.port'] == 5432, "INI int not coerced"
        assert ini_config['database.timeout'] == 2.5, "INI float not coerced"
        assert ini_config['database.enabled'] is True, "INI yes not coerced"
        assert ini_config['app.name'] == 'ini-app'

        # Test 9: INI env override still applies
        os.environ['APP_DATABASE_PORT'] = '9999'
        try:
            ini_env = load_config(ini_path, env_prefix='APP_')
            assert ini_env['database.port'] == 9999, "env override on INI failed"
        finally:
            del os.environ['APP_DATABASE_PORT']


if __name__ == "__main__":
    _selftest()
