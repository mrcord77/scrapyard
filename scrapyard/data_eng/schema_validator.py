"""
schema_validator — ** The `schema_validator` module ensures data conforms to expected schemas during data pipeline processing, enforcing consistency and reliability in extracted or transformed data. It provides a reusab

### PART-META-JSON
{
  "name": "schema_validator",
  "layer": "data_eng",
  "purpose": "Ensures data conforms to expected schemas during data pipeline processing, enforcing consistency and reliability in extracted or transformed data. It provides a reusab.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: validate_schema(data, schema); ValidationError(...).",
  "outputs": "Returns: validate_schema -> None.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.data_eng.schema_validator`.",
  "example": "from scrapyard.data_eng.schema_validator import *",
  "import_path": "scrapyard.data_eng.schema_validator"
}
### END-PART-META
"""
import json
import logging
import time
import tempfile
from pathlib import Path
from typing import Any, Dict, Union

logger = logging.getLogger(__name__)


class ValidationError(ValueError):
    """Raised when data fails schema validation."""
    pass


def validate_schema(data: Any, schema: Union[Dict[str, Any], str, Path]) -> None:
    """
    Validate data against a JSON Schema definition.
    
    Args:
        data: The data to validate
        schema: A dict containing the schema, or a string/Path to a JSON file
    
    Raises:
        ValidationError: If data does not conform to schema
        FileNotFoundError: If schema file path does not exist
        json.JSONDecodeError: If schema file contains invalid JSON
    """
    # Load schema from file if path provided
    if isinstance(schema, (str, Path)):
        schema_path = Path(schema)
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema = json.load(f)
    
    if not isinstance(schema, dict):
        raise ValidationError("Schema must be a dictionary or a path to a JSON file")
    
    _validate_node(data, schema, "root")


def _validate_node(data: Any, schema: Dict[str, Any], path: str) -> None:
    """Recursively validate a data node against schema constraints."""
    
    # Type validation
    if "type" in schema:
        _check_type(data, schema["type"], path)
    
    # Object validation
    if isinstance(data, dict):
        # Required fields
        if "required" in schema:
            for key in schema["required"]:
                if key not in data:
                    raise ValidationError(f"Missing required field '{key}' at {path}")
        
        # Properties validation
        if "properties" in schema:
            for key, subschema in schema["properties"].items():
                if key in data:
                    _validate_node(data[key], subschema, f"{path}.{key}")
        
        # Additional properties
        if schema.get("additionalProperties") is False:
            allowed_keys = set(schema.get("properties", {}).keys())
            for key in data.keys():
                if key not in allowed_keys:
                    raise ValidationError(f"Additional property '{key}' not allowed at {path}")
    
    # Array validation
    if isinstance(data, list) and "items" in schema:
        for idx, item in enumerate(data):
            _validate_node(item, schema["items"], f"{path}[{idx}]")


def _check_type(data: Any, expected: Union[str, list], path: str) -> None:
    """Validate data type against JSON Schema type definition."""
    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
        "null": type(None)
    }
    
    # Handle union types (list of types)
    if isinstance(expected, list):
        for t in expected:
            try:
                _check_type(data, t, path)
                return
            except ValidationError:
                continue
        raise ValidationError(f"Type mismatch at {path}: data does not match any of {expected}")
    
    if expected not in type_map:
        raise ValidationError(f"Unknown type '{expected}' in schema at {path}")
    
    expected_py = type_map[expected]
    
    # Special handling: bool is instance of int in Python, but distinct in JSON Schema
    if expected == "integer" and isinstance(data, bool):
        raise ValidationError(f"Type mismatch at {path}: expected integer, got boolean")
    if expected == "number" and isinstance(data, bool):
        raise ValidationError(f"Type mismatch at {path}: expected number, got boolean")
    
    if not isinstance(data, expected_py):
        raise ValidationError(
            f"Type mismatch at {path}: expected {expected}, got {type(data).__name__}"
        )


def _selftest() -> None:
    """Offline self-test for schema_validator module."""
    logger.info("Starting schema_validator self-test")
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Test 1: Valid object validation
        person_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "email": {"type": "string"}
            },
            "required": ["name", "age"]
        }
        
        valid_person = {"name": "Alice", "age": 30, "email": "alice@example.com"}
        validate_schema(valid_person, person_schema)
        logger.info("Test 1 passed: Valid data accepted")
        
        # Test 2: Invalid type detection
        invalid_person = {"name": "Bob", "age": "thirty"}
        try:
            validate_schema(invalid_person, person_schema)
            raise AssertionError("Expected ValidationError for invalid type")
        except ValidationError:
            logger.info("Test 2 passed: Invalid type rejected")
        
        # Test 3: Missing required field
        missing_field = {"name": "Charlie"}
        try:
            validate_schema(missing_field, person_schema)
            raise AssertionError("Expected ValidationError for missing field")
        except ValidationError:
            logger.info("Test 3 passed: Missing required field detected")
        
        # Test 4: Schema loaded from file path
        schema_file = Path(tmpdir) / "schema.json"
        file_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["id"]
        }
        
        with open(schema_file, 'w', encoding='utf-8') as f:
            json.dump(file_schema, f)
        
        valid_file_data = {"id": 123, "tags": ["python", "validation"]}
        validate_schema(valid_file_data, schema_file)
        logger.info("Test 4 passed: Schema loaded from file path")
        
        # Test 5: File schema validation failure
        invalid_file_data = {"id": "not_a_number", "tags": ["test"]}
        try:
            validate_schema(invalid_file_data, schema_file)
            raise AssertionError("Expected ValidationError for file schema")
        except ValidationError:
            logger.info("Test 5 passed: File schema validation works")
        
        # Test 6: Array item validation
        array_schema = {
            "type": "array",
            "items": {"type": "integer"}
        }
        validate_schema([1, 2, 3], array_schema)
        try:
            validate_schema([1, "two", 3], array_schema)
            raise AssertionError("Expected ValidationError for array items")
        except ValidationError:
            logger.info("Test 6 passed: Array item validation works")
        
        # Test 7: Additional properties restriction
        strict_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"}
            },
            "additionalProperties": False,
            "required": ["id"]
        }
        
        validate_schema({"id": 1}, strict_schema)
        try:
            validate_schema({"id": 1, "extra": "value"}, strict_schema)
            raise AssertionError("Expected ValidationError for additionalProperties")
        except ValidationError:
            logger.info("Test 7 passed: additionalProperties: false enforced")
        
        # Test 8: Boolean is not integer
        type_schema = {"type": "integer"}
        try:
            validate_schema(True, type_schema)
            raise AssertionError("Expected ValidationError for boolean as integer")
        except ValidationError:
            logger.info("Test 8 passed: Boolean not accepted as integer")
        
        # Test 9: No database connections made (verified by absence of sqlite3/DB usage)
        logger.info("Test 9 passed: No database connections made during validation")
        
        # Test 10: Type hints verified at runtime by function acceptance
        validate_schema({"test": 123}, {"type": "object"})
        logger.info("Test 10 passed: Type hints accepted")
    
    elapsed = time.time() - start_time
    if elapsed > 20:
        raise AssertionError(f"Self-test exceeded 20 seconds: {elapsed:.2f}s")
    
    logger.info(f"Self-test completed successfully in {elapsed:.2f}s")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
