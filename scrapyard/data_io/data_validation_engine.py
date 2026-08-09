"""
data_validation_engine — ** The `Validator` class ensures data integrity by enforcing schema and business rules during import/export operations. It provides a reusable, rule-based validation engine for structured data process

### PART-META-JSON
{
  "name": "data_validation_engine",
  "layer": "data_io",
  "purpose": "The `Validator` class ensures data integrity by enforcing schema and business rules during import/export operations. It provides a reusable, rule-based validation engine for structured data process.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: Error(...); Validator(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.data_io.data_validation_engine`.",
  "example": "from scrapyard.data_io.data_validation_engine import *",
  "import_path": "scrapyard.data_io.data_validation_engine"
}
### END-PART-META
"""
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Dict, Callable
import logging

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class Error:
    message: str
    code: int
    path: List[str]

class Validator:
    def __init__(self, schema: Dict, rules: List[Callable]) -> None:
        self.schema = schema
        self.rules = rules

    def validate_record(self, record: Dict) -> List[Error]:
        errors = []
        
        # Validate against schema
        for field_name, field_type in self.schema.items():
            if field_name not in record:
                errors.append(Error(f"Missing required field {field_name}", 4001, [field_name]))
            elif not isinstance(record[field_name], field_type):
                errors.append(Error(f"Incorrect type for field {field_name}: expected {field_type.__name__}, got {type(record[field_name]).__name__}", 4002, [field_name]))

        # Apply business rules
        for rule in self.rules:
            try:
                if not rule(record):
                    errors.append(Error(f"Failed business rule: {rule.__name__}", 4003, ["business_rule"]))
            except Exception as e:
                logger.error(f"Error applying rule {rule.__name__}: {e}")
                errors.append(Error(f"Error applying rule {rule.__name__}: {str(e)}", 5001, [f"business_rule_{rule.__name__}"]))

        return errors

def _selftest():
    # Define a simple schema
    schema = {
        "id": int,
        "name": str,
        "price": float,
        "in_stock": bool,
        "created_at": datetime,
    }

    # Define some business rules
    def must_have_name(record):
        return record.get("name", "") != ""

    def price_must_be_positive(record):
        return record["price"] > 0

    rules = [must_have_name, price_must_be_positive]

    validator = Validator(schema=schema, rules=rules)

    # Test cases
    test_cases = [
        {"id": 1, "name": "Widget", "price": 9.99, "in_stock": True, "created_at": datetime.now(timezone.utc)},
        {"id": 2},
        {"id": 3, "name": "", "price": -10.0, "in_stock": False, "created_at": datetime.now(timezone.utc)},
    ]

    # 1) A fully valid record passes with zero errors.
    good = {"id": 1, "name": "Widget", "price": 9.99, "in_stock": True,
            "created_at": datetime.now(timezone.utc)}
    assert validator.validate_record(good) == [], validator.validate_record(good)

    # 2) Missing required fields are reported with the schema-missing code (4001),
    #    one per absent field, each naming the field in its path.
    errs_missing = validator.validate_record({"id": 2})
    missing_codes = [e for e in errs_missing if e.code == 4001]
    missing_fields = {e.path[0] for e in missing_codes}
    assert missing_fields == {"name", "price", "in_stock", "created_at"}, missing_fields

    # 3) A wrong type is reported with the type-mismatch code (4002) and the reason
    #    references both expected and actual types.
    errs_type = validator.validate_record(
        {"id": 3, "name": "X", "price": "not-a-float", "in_stock": True,
         "created_at": datetime.now(timezone.utc)})
    type_errs = [e for e in errs_type if e.code == 4002 and e.path == ["price"]]
    assert type_errs, f"expected a type error for price, got {errs_type}"
    assert "float" in type_errs[0].message and "str" in type_errs[0].message

    # 4) Negative/adversarial: business rules fire on an empty name and a negative
    #    price (code 4003), independent of schema type checks.
    errs_rules = validator.validate_record(
        {"id": 4, "name": "", "price": -10.0, "in_stock": False,
         "created_at": datetime.now(timezone.utc)})
    failed_rules = {e.message for e in errs_rules if e.code == 4003}
    assert any("must_have_name" in m for m in failed_rules), failed_rules
    assert any("price_must_be_positive" in m for m in failed_rules), failed_rules

    print("data_validation_engine selftest: PASS")

if __name__ == "__main__":
    _selftest()
