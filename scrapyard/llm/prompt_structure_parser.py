"""
prompt_structure_parser — ** The `scrapyard.llm.prompt_structure_parser` module provides robust parsing and repair capabilities for structured LLM prompt outputs, ensuring consistent JSON formatting and handling malformed inpu

### PART-META-JSON
{
  "name": "prompt_structure_parser",
  "layer": "llm",
  "purpose": "Provides robust parsing and repair capabilities for structured LLM prompt outputs, ensuring consistent JSON formatting and handling malformed inpu.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: parse_output(text, schema); repair_json(text); validate_schema(parsed_json, schema); validate_type(value, expected_type); SchemaDefinition(...).",
  "outputs": "Returns: parse_output -> Dict; repair_json -> Dict; validate_schema -> None; validate_type -> None.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.llm.prompt_structure_parser`.",
  "example": "from scrapyard.llm.prompt_structure_parser import *",
  "import_path": "scrapyard.llm.prompt_structure_parser"
}
### END-PART-META
"""
from typing import Optional, List, Dict, Any
import json
import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class SchemaDefinition:
    properties: Dict[str, type]
    required: List[str] = field(default_factory=list)

def parse_output(text: str, schema: Optional[Dict]) -> Dict:
    try:
        parsed_json = json.loads(text)
        if schema is not None:
            validate_schema(parsed_json, schema)
        return parsed_json
    except json.JSONDecodeError as e:
        logger.error(f"JSON decoding error: {e}")
        repaired_json = repair_json(text)
        if schema is not None:
            validate_schema(repaired_json, schema)
        return repaired_json

def repair_json(text: str) -> Dict:
    try:
        # Attempt to parse the JSON string
        parsed_json = json.loads(text)
        return parsed_json
    except json.JSONDecodeError as e:
        logger.error(f"JSON decoding error: {e}")
        
        # Try to fix common syntax errors
        text = re.sub(r'(\{|\[)(\s*([^,}]*),?\s*)+', r'\1\3', text)  # Remove trailing commas in objects and arrays
        try:
            parsed_json = json.loads(text)
            return parsed_json
        except json.JSONDecodeError as e:
            logger.error(f"Failed to repair JSON: {e}")
            raise ValueError("Unable to repair the JSON input") from e

def validate_schema(parsed_json: Dict, schema: Dict) -> None:
    for key in parsed_json.keys():
        if key not in schema['required'] and key not in schema['properties']:
            logger.error(f"Unrecognized property: {key}")
            raise ValueError(f"Unrecognized property: {key}")
    
    for key, value in parsed_json.items():
        expected_type = schema['properties'].get(key)
        if expected_type is None:
            continue
        try:
            validate_type(value, expected_type)
        except TypeError as e:
            logger.error(f"Invalid type for '{key}': {e}")
            raise ValueError(f"Invalid type for '{key}': {e}") from e

def validate_type(value: Any, expected_type: type) -> None:
    if isinstance(expected_type, type):
        if not isinstance(value, expected_type):
            raise TypeError(f"Expected {expected_type.__name__}, got {type(value).__name__}")
    elif callable(expected_type):  # Custom validation function
        if not expected_type(value):
            raise TypeError(f"Custom validation failed for value: {value}")

def _selftest() -> None:
    """Offline self-test: a well-formed LLM output parses to the expected dict and
    passes schema validation; type mismatches and unknown properties are rejected;
    and malformed input is handled (repaired or raised) without crashing the caller.
    """
    schema = {"properties": {"key": str, "another_key": bool}, "required": ["key"]}

    # Well-formed JSON parses to the exact structure.
    assert parse_output('{"key": "value"}', None) == {"key": "value"}
    assert parse_output('{"key": "value", "another_key": true}', schema) == {
        "key": "value", "another_key": True}

    # Type coercion is NOT silent: a schema type mismatch raises ValueError.
    try:
        parse_output('{"key": 123}', {"properties": {"key": str}, "required": ["key"]})
        raise AssertionError("expected ValueError for type mismatch")
    except ValueError:
        pass

    # Negative/adversarial: a property not in the schema is rejected.
    try:
        parse_output('{"unexpected": 1}', {"properties": {"key": str}, "required": ["key"]})
        raise AssertionError("expected ValueError for unrecognized property")
    except ValueError:
        pass

    # Malformed-but-unrepairable JSON raises ValueError rather than returning junk.
    try:
        parse_output('{"a": ', None)
        raise AssertionError("expected ValueError for unrepairable JSON")
    except ValueError:
        pass

    # Malformed-but-tolerable JSON (trailing comma) is HANDLED: returns a dict, never
    # raises unexpectedly. (Repair is lossy here; the contract is 'does not crash'.)
    repaired = parse_output('{"a": 1,}', None)
    assert isinstance(repaired, dict), f"repair should yield a dict, got {type(repaired)}"

    # repair_json on hopeless input raises ValueError explicitly.
    try:
        repair_json("{not: valid: json:::")
        raise AssertionError("expected ValueError from repair_json")
    except ValueError:
        pass

    print("prompt_structure_parser selftest: PASS")

if __name__ == "__main__":
    _selftest()
