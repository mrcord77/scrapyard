"""
data_mapping_loader — ** The `scrapyard.data_io.data_mapping_loader` module provides a flexible and reusable mechanism for loading and parsing data mapping configurations from external files. It enables consistent and type

### PART-META-JSON
{
  "name": "data_mapping_loader",
  "layer": "data_io",
  "purpose": "Provides a flexible and reusable mechanism for loading and parsing data mapping configurations from external files. It enables consistent and type.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: MappingLoader(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.data_io.data_mapping_loader`.",
  "example": "from scrapyard.data_io.data_mapping_loader import *",
  "import_path": "scrapyard.data_io.data_mapping_loader"
}
### END-PART-META
"""
import os
import json
from typing import Optional
import logging
from tempfile import TemporaryDirectory
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    from jsonschema import validate as schema_validate, ValidationError
except ImportError:
    raise ImportError("jsonschema is required for this module to function")


@dataclass
class MappingLoader:
    config_path: Optional[str] = None

    def __post_init__(self):
        if self.config_path and not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file {self.config_path} does not exist")

    @staticmethod
    def load_mapping_from_file(file_path: str) -> dict:
        with open(file_path, 'r') as f:
            content = f.read()
        if file_path.endswith('.json'):
            mapping = json.loads(content)
        elif file_path.endswith('.yaml') or file_path.endswith('.yml'):
            # Assuming a YAML loader is available
            import yaml
            mapping = yaml.safe_load(content)
        else:
            raise ValueError(f"Unsupported file format: {file_path}")
        return mapping

    @staticmethod
    def validate_mapping(mapping: dict) -> bool:
        schema = {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "target": {"type": "string"},
                "transform": {"type": "array", "items": {"type": "string"}},
                "options": {"type": "object"}
            },
            "required": ["source", "target"]
        }
        try:
            schema_validate(instance=mapping, schema=schema)
            return True
        except ValidationError as e:
            logger.error(f"Mapping validation failed: {e}")
            return False


def _selftest():
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        # Create a temporary YAML file for testing
        test_yaml = os.path.join(tmp_dir, 'test_mapping.yaml')
        with open(test_yaml, 'w') as f:
            f.write("""
source: "user_id"
target: "id"
transform: ["str.lower"]
options: {"nullable": true}
""")

        # Create a temporary JSON file for testing
        test_json = os.path.join(tmp_dir, 'test_mapping.json')
        with open(test_json, 'w') as f:
            json.dump({
                "source": "user_id",
                "target": "id",
                "transform": ["str.lower"],
                "options": {"nullable": True}
            }, f)

        # Test YAML loading
        loader = MappingLoader()
        mapping_yaml = loader.load_mapping_from_file(test_yaml)
        assert mapping_yaml == {
            "source": "user_id",
            "target": "id",
            "transform": ["str.lower"],
            "options": {"nullable": True}
        }, f"YAML load failed: {mapping_yaml}"

        # Test JSON loading
        mapping_json = loader.load_mapping_from_file(test_json)
        assert mapping_json == {
            "source": "user_id",
            "target": "id",
            "transform": ["str.lower"],
            "options": {"nullable": True}
        }, f"JSON load failed: {mapping_json}"

        # Test validation
        valid_mapping = {
            "source": "user_id",
            "target": "id",
            "transform": [],
            "options": {}
        }
        assert loader.validate_mapping(valid_mapping), "Valid mapping should pass validation"

        invalid_mapping = {"invalid_key": "value"}
        assert not loader.validate_mapping(invalid_mapping), "Invalid mapping should fail validation"

    logger.info("_selftest passed successfully")


if __name__ == "__main__":
    _selftest()
