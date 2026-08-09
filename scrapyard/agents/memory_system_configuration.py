"""
memory_system_configuration — Central store for agent memory-system parameters (recall threshold, forgetting-policy configs) persisted to a configurable JSON file, so recall scoring and forgetting behavior can be tuned without code changes.

### PART-META-JSON
{
  "name": "memory_system_configuration",
  "layer": "agents",
  "purpose": "Centralizes agent memory-system parameters: a recall threshold (0..1) and per-policy forgetting configurations ('linear'/'exponential'), persisted as JSON at a configurable path so memory_recall_scoring and forgetting_policy_manager consumers share one tunable source of truth.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "set_config_path(path); set_recall_threshold(0..1); configure_forgetting_policy('linear'|'exponential', **params); get_config().",
  "outputs": "MemorySystemConfig dataclass (recall_threshold, forgetting_policy_configs); JSON file at the configured path.",
  "files_created": [
    "memory_system_config.json (at the configured path; default is the process working directory)"
  ],
  "security_notes": "The config file is written wherever set_config_path() points, so point it inside your project state directory (never a shared/world-writable location) and treat its contents as untrusted on load: get_config() falls back to safe defaults on missing/corrupt JSON instead of crashing, and thresholds are validated to [0,1]. No secrets belong in this file.",
  "ai_usage": "from scrapyard.agents.memory_system_configuration import set_config_path, set_recall_threshold, get_config; set_config_path(state_dir / 'memory_system_config.json'); set_recall_threshold(0.8).",
  "example": "from scrapyard.agents.memory_system_configuration import get_config",
  "import_path": "scrapyard.agents.memory_system_configuration"
}
### END-PART-META
"""
from dataclasses import dataclass, field
from typing import Dict, Any
import json, logging, os

logger = logging.getLogger(__name__)

# Configurable persistence location (the old behavior hardcoded a file in the
# process CWD, which polluted whatever directory the host app ran from and made
# repeated runs order-dependent).
_DEFAULT_CONFIG_PATH = "memory_system_config.json"
_config_path = _DEFAULT_CONFIG_PATH


def set_config_path(path: str) -> None:
    """Point the module at a specific config file location."""
    global _config_path
    if not path or not isinstance(path, (str, os.PathLike)):
        raise ValueError("Config path must be a non-empty string or path")
    _config_path = os.fspath(path)


def get_config_path() -> str:
    return _config_path


@dataclass
class MemorySystemConfig:
    recall_threshold: float = 0.75
    forgetting_policy_configs: Dict[str, Dict] = field(default_factory=dict)


def set_recall_threshold(threshold: float) -> None:
    if not (0 <= threshold <= 1):
        raise ValueError("Recall threshold must be between 0 and 1")
    config = get_config()
    config.recall_threshold = threshold
    save_config(config)


def configure_forgetting_policy(policy_name: str, **kwargs: Any) -> None:
    if policy_name not in ["linear", "exponential"]:
        raise ValueError("Invalid forgetting policy name. Choose 'linear' or 'exponential'")
    config = get_config()
    config.forgetting_policy_configs[policy_name] = kwargs
    save_config(config)


def get_config() -> MemorySystemConfig:
    try:
        with open(_config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return MemorySystemConfig(**data)
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return MemorySystemConfig()


def save_config(config: MemorySystemConfig) -> None:
    with open(_config_path, 'w', encoding='utf-8') as f:
        json.dump(config.__dict__, f)


def _selftest() -> bool:
    import tempfile
    global _config_path
    prior_path = _config_path
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        set_config_path(os.path.join(tmpdir, "memory_system_config.json"))
        try:
            config = get_config()
            assert config.recall_threshold == 0.75
            assert not config.forgetting_policy_configs

            set_recall_threshold(0.8)
            config = get_config()
            assert config.recall_threshold == 0.8

            configure_forgetting_policy("linear", half_life=10)
            config = get_config()
            assert config.forgetting_policy_configs["linear"] == {"half_life": 10}

            try:
                set_recall_threshold(-0.1)
                raise AssertionError("Expected ValueError for threshold out of range")
            except ValueError as e:
                assert str(e) == "Recall threshold must be between 0 and 1"

            try:
                configure_forgetting_policy("invalid", half_life=10)
                raise AssertionError("Expected ValueError for invalid policy")
            except ValueError as e:
                assert str(e) == "Invalid forgetting policy name. Choose 'linear' or 'exponential'"

            # Corrupt config file falls back to defaults instead of crashing.
            with open(_config_path, 'w', encoding='utf-8') as f:
                f.write("{not json")
            assert get_config().recall_threshold == 0.75
        finally:
            _config_path = prior_path

    return True

if __name__ == "__main__":
    if _selftest():
        logger.info("Self-test passed successfully.")
    else:
        logger.error("Self-test failed.")
