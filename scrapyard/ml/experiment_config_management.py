"""
experiment_config_management — Manages experiment configurations and hyperparameters in a structured and reusable way, ensuring consistency and traceability across ML training workflows.

### PART-META-JSON
{
  "name": "experiment_config_management",
  "layer": "ml",
  "purpose": "Manages experiment configurations and hyperparameters in a structured and reusable way, ensuring consistency and traceability across ML training workflows.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "metric_tracking",
    "lr_schedulers"
  ],
  "inputs": "Public API: ConfigManager(...); HyperParamScheduler(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.ml.experiment_config_management`.",
  "example": "from scrapyard.ml.experiment_config_management import *",
  "import_path": "scrapyard.ml.experiment_config_management"
}
### END-PART-META
"""

from dataclasses import dataclass
from typing import Dict, Any, Callable
import os, json, logging, tempfile

logger = logging.getLogger(__name__)

@dataclass
class ConfigManager:
    config_path: str
    default_config: Dict[str, Any]

    def __post_init__(self):
        self._config_id_counter = 0
        self._configs = {}

    def load_config(self, config_id: str) -> Dict[str, Any]:
        if config_id in self._configs:
            return self._configs[config_id]
        
        if not os.path.exists(self.config_path):
            raise ValueError(f"Config ID {config_id} not found")
            
        with open(self.config_path, 'r') as f:
            configs = json.load(f)
            for id_, config in configs.items():
                if id_ == config_id:
                    self._configs[id_] = config
                    return config
        raise ValueError(f"Config ID {config_id} not found")

    def save_config(self, config: Dict[str, Any]) -> str:
        new_id = f"config_{self._config_id_counter}"
        self._config_id_counter += 1
        
        configs = {}
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                configs = json.load(f)
        
        configs[new_id] = config
        with open(self.config_path, 'w') as f:
            json.dump(configs, f, indent=2)
        
        self._configs[new_id] = config
        return new_id

    def get_default_config(self) -> Dict[str, Any]:
        return self.default_config

    def apply_overrides(self, config: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
        result = config.copy()
        for key, value in overrides.items():
            if isinstance(value, Callable):
                result[key] = value()
            else:
                result[key] = value
        return result


@dataclass
class HyperParamScheduler:
    scheduler_type: str
    params: Dict[str, Any]

    def __post_init__(self):
        self._current_value = 0

    def get_next_value(self, step: int) -> float:
        if self.scheduler_type == "linear":
            value = (step / 100.0) * self.params.get("max_value", 1.0)
        elif self.scheduler_type == "exponential":
            value = self.params["base"] ** (step / self.params.get("rate", 10))
        else:
            raise ValueError(f"Unsupported scheduler type: {self.scheduler_type}")
        return round(value, 10)

    def reset(self) -> None:
        self._current_value = 0


def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        config_path = os.path.join(tmpdir, "configs.json")
        default_config = {"learning_rate": 0.1, "batch_size": 32}
        
        # Test ConfigManager
        cm = ConfigManager(config_path, default_config)
        config_id = cm.save_config({"learning_rate": 0.05, "batch_size": 64})
        assert cm.load_config(config_id) == {"learning_rate": 0.05, "batch_size": 64}
        
        # Test HyperParamScheduler
        scheduler = HyperParamScheduler("linear", {"max_value": 0.2})
        assert scheduler.get_next_value(10) == 0.02
        scheduler.reset()
        assert scheduler._current_value == 0
        
        # Test apply_overrides
        config = cm.load_config(config_id)
        overrides = {"learning_rate": lambda: 0.07, "batch_size": 128}
        new_config = cm.apply_overrides(config, overrides)
        assert new_config["learning_rate"] == 0.07
        assert new_config["batch_size"] == 128



if __name__ == "__main__":
    _selftest()
