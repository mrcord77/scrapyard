"""
data_export_formatter — ** The `scrapyard.data_io.data_export_formatter` module provides a reusable, type-safe interface for formatting structured data into standardized export formats like CSV or JSON. It ensures consistent

### PART-META-JSON
{
  "name": "data_export_formatter",
  "layer": "data_io",
  "purpose": "Provides a reusable, type-safe interface for formatting structured data into standardized export formats like CSV or JSON. It ensures consistent.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: ExportFormatter(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.data_io.data_export_formatter`.",
  "example": "from scrapyard.data_io.data_export_formatter import *",
  "import_path": "scrapyard.data_io.data_export_formatter"
}
### END-PART-META
"""
from typing import Optional, List, Dict, Any, Union
import json
import tempfile
import logging

# Set up basic logger configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ExportFormatter:
    def __init__(self, format: str, schema: Optional[Dict[str, Any]] = None):
        self.format = format
        self.schema = schema or {}
    
    @staticmethod
    def _validate_schema(data: List[Dict[str, Any]], schema: Dict[str, Any]):
        for entry in data:
            for key, expected_type in schema.items():
                if key not in entry:
                    raise ValueError(f"Missing required field '{key}'")
                if not isinstance(entry[key], expected_type):
                    actual_type = type(entry[key])
                    raise TypeError(f"Field '{key}' should be of type {expected_type} but is {actual_type}")

    def format_for_export(self, data: List[Dict[str, Any]]) -> Union[str, bytes]:
        self._validate_schema(data, self.schema)
        
        if self.format == 'csv':
            return self._format_to_csv(data)
        elif self.format == 'json':
            return json.dumps(data, indent=4).encode('utf-8')
        else:
            raise ValueError(f"Unsupported format '{self.format}'")

    @staticmethod
    def _format_to_csv(data: List[Dict[str, Any]]) -> str:
        header = ','.join(sorted(set(key for d in data for key in d.keys())))
        rows = [header]
        
        for entry in sorted(data, key=lambda x: tuple(x.values())):
            row_values = [str(entry.get(key, '')) for key in header.split(',')]
            rows.append(','.join(row_values))
        
        return '\n'.join(rows)

def _selftest():
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    
    # Test data
    test_data_csv = [
        {"name": "Part A", "quantity": 10, "price": 50.5},
        {"name": "Part B", "quantity": 20, "price": 75.3}
    ]
    
    test_data_json = [
        {"id": 1, "part_name": "Wheel", "description": "Steel wheel"},
        {"id": 2, "part_name": "Bolt", "description": "Steel bolt"}
    ]
    
    # Test schema
    csv_schema = {
        "name": str,
        "quantity": int,
        "price": float
    }
    
    json_schema = {
        "id": int,
        "part_name": str,
        "description": str
    }
    
    try:
        # CSV test
        formatter_csv = ExportFormatter(format='csv', schema=csv_schema)
        formatted_csv = formatter_csv.format_for_export(test_data_csv)
        assert 'name,quantity,price' in formatted_csv
        assert 'Part A,10,50.5' in formatted_csv
        
        # JSON test
        formatter_json = ExportFormatter(format='json', schema=json_schema)
        formatted_json = formatter_json.format_for_export(test_data_json)
        json.loads(formatted_json.decode('utf-8'))
        
        logger.info("Self-test passed successfully.")
    except Exception as e:
        logger.error(f"Self-test failed: {e}")
    finally:
        temp_dir.cleanup()

if __name__ == "__main__":
    _selftest()
