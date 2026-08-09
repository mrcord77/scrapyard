"""
model_factory — The `model_factory` module provides a reusable system for dynamically instantiating machine learning models based on configuration specifications, enabling flexible and decoupled model creation in tra

### PART-META-JSON
{
  "name": "model_factory",
  "layer": "ml",
  "purpose": "The `model_factory` module provides a reusable system for dynamically instantiating machine learning models based on configuration specifications, enabling flexible and decoupled model creation in tra",
  "addition": true,
  "status": "core",
  "dependencies": [
    "experiment_config_management"
  ],
  "inputs": "Public API: ModelSpecParser(...); ModelFactory(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.model_factory`.",
  "example": "from scrapyard.ml.model_factory import *",
  "import_path": "scrapyard.ml.model_factory"
}
### END-PART-META
"""

from typing import Dict, Any, Callable
import json
import logging

logger = logging.getLogger(__name__)

class ModelSpecParser:
    def parse(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        parsed_spec = {}
        for key, value in spec.items():
            if isinstance(value, str):
                try:
                    parsed_value = json.loads(value)
                except json.JSONDecodeError:
                    parsed_value = value
            else:
                parsed_value = value
            parsed_spec[key] = parsed_value
        return parsed_spec

    def validate(self, spec: Dict[str, Any]) -> None:
        required_keys = {"model_type", "hyperparameters"}
        if not required_keys.issubset(spec.keys()):
            raise ValueError("Missing required keys in model specification")

class ModelFactory:
    def __init__(self, config_parser: ModelSpecParser, registry: Dict[str, Callable[..., Any]]) -> None:
        self.config_parser = config_parser
        self.registry = registry

    def build_model(self, spec: Dict[str, Any]) -> Any:
        parsed_spec = self.config_parser.parse(spec)
        self.config_parser.validate(parsed_spec)

        model_type = parsed_spec.get("model_type")
        if model_type not in self.registry:
            raise ValueError(f"Unknown model type: {model_type}")

        hyperparameters = parsed_spec.get("hyperparameters", {})
        return self.registry[model_type](**hyperparameters)

def _selftest():
    from scrapyard.ml.model_factory import ModelFactory, ModelSpecParser
    from unittest.mock import MagicMock

    # Mock registry and models
    mock_registry = {
        "linear_regression": MagicMock(),
        "decision_tree": MagicMock()
    }

    # Create parsers and factory
    config_parser = ModelSpecParser()
    model_factory = ModelFactory(config_parser, mock_registry)

    # Test valid spec
    valid_spec = {
        "model_type": "linear_regression",
        "hyperparameters": {"learning_rate": 0.1}
    }
    model = model_factory.build_model(valid_spec)
    assert isinstance(model, MagicMock), "Model should be an instance of the registered model"

    # Test invalid spec - missing model type
    invalid_spec_missing_type = {
        "hyperparameters": {"learning_rate": 0.1}
    }
    try:
        model_factory.build_model(invalid_spec_missing_type)
        assert False, "Should raise ValueError for missing model type"
    except ValueError as e:
        assert str(e) == "Missing required keys in model specification", f"Unexpected error: {e}"

    # Test invalid spec - unknown model type
    invalid_spec_unknown_type = {
        "model_type": "unknown_model",
        "hyperparameters": {"learning_rate": 0.1}
    }
    try:
        model_factory.build_model(invalid_spec_unknown_type)
        assert False, "Should raise ValueError for unknown model type"
    except ValueError as e:
        assert str(e) == "Unknown model type: unknown_model", f"Unexpected error: {e}"

if __name__ == "__main__":
    _selftest()
