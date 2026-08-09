"""
transformer — ** The `scrapyard.data_eng.transformer` module provides reusable data transformation logic for data pipelines, ensuring consistency and integrity before data is loaded into storage. It supports schema

### PART-META-JSON
{
  "name": "transformer",
  "layer": "data_eng",
  "purpose": "Provides reusable data transformation logic for data pipelines, ensuring consistency and integrity before data is loaded into storage. It supports schema.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: apply_transformations(data, rules); validate_schema(data, schema); deduplicate(data, key_fields).",
  "outputs": "Returns: apply_transformations -> List[Dict]; validate_schema -> bool; deduplicate -> List[Dict].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.data_eng.transformer`.",
  "example": "from scrapyard.data_eng.transformer import *",
  "import_path": "scrapyard.data_eng.transformer"
}
### END-PART-META
"""
from typing import List, Dict, Any, Callable
import logging

logger = logging.getLogger(__name__)

def apply_transformations(data: List[Dict], rules: List[Callable]) -> List[Dict]:
    """
    Apply a series of transformation functions to the input data.
    
    :param data: List of dictionaries representing the raw data.
    :param rules: List of callable transformation functions.
    :return: Transformed list of dictionaries.
    """
    for rule in rules:
        data = [rule(item) for item in data]
    return data

def validate_schema(data: List[Dict], schema: Dict[str, Any]) -> bool:
    """
    Validate the input data against a given schema with strict type checking.
    
    :param data: List of dictionaries representing the raw data.
    :param schema: Dictionary defining the expected structure and types.
    :return: True if all items in `data` match the schema, False otherwise.
    """
    for item in data:
        try:
            for key, value_type in schema.items():
                if key not in item or not isinstance(item[key], value_type):
                    return False
        except KeyError as e:
            logger.error(f"Schema validation failed: {e}")
            return False
    return True

def deduplicate(data: List[Dict], key_fields: List[str]) -> List[Dict]:
    """
    Remove duplicate entries based on specified key fields.
    
    :param data: List of dictionaries representing the raw data.
    :param key_fields: List of field names to use for deduplication.
    :return: Deduplicated list of dictionaries.
    """
    seen = set()
    unique_data = []
    for item in data:
        key = tuple(item.get(field) for field in key_fields)
        if key not in seen:
            seen.add(key)
            unique_data.append(item)
    return unique_data

def _selftest():
    # Sample data and rules
    sample_data = [
        {"id": 1, "name": "part1", "price": 10.5},
        {"id": 2, "name": "part2", "price": 20.5},
        {"id": 1, "name": "part1", "price": 10.5},  # Duplicate
    ]
    
    schema = {
        "id": int,
        "name": str,
        "price": float,
    }
    
    rules = [
        lambda x: {**x, "new_field": f"transformed_{x['name']}"},
        lambda x: {k: v.upper() if isinstance(v, str) else v for k, v in x.items()},
    ]
    
    # Validate schema
    assert validate_schema(sample_data, schema), "Schema validation failed"
    
    # Apply transformations
    transformed_data = apply_transformations(sample_data, rules)
    assert len(transformed_data) == 3, "Transformation applied incorrectly"
    
    # Deduplicate data
    deduplicated_data = deduplicate(transformed_data, ["id"])
    assert len(deduplicated_data) == 2, "Deduplication failed"
    
    logger.info("Self-test passed successfully")

if __name__ == "__main__":
    _selftest()
