"""
argument_schemas_validator — Validate input arguments against predefined schemas to ensure correctness and consistency in skill execution, supporting dynamic schema validation and schema versioning.

### PART-META-JSON
{
  "name": "argument_schemas_validator",
  "layer": "skills",
  "purpose": "Validate input arguments against predefined schemas to ensure correctness and consistency in skill execution, supporting dynamic schema validation and schema versioning.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: validate_args(args, schema); ArgumentSchema(...).",
  "outputs": "Returns: validate_args -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.skills.argument_schemas_validator`.",
  "example": "from scrapyard.skills.argument_schemas_validator import *",
  "import_path": "scrapyard.skills.argument_schemas_validator"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, JSON, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


class ArgumentSchema(IntPKModel):
    """Schema definition for argument validation."""
    
    __tablename__ = "argument_schemas"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)


def validate_args(args: Any, schema: ArgumentSchema) -> None:
    """
    Validate input arguments against an ArgumentSchema definition.
    
    Args:
        args: The arguments to validate (typically a dict)
        schema: The ArgumentSchema instance containing the schema definition
        
    Raises:
        TypeError: If args does not match the expected type
        ValueError: If args violates schema constraints (missing keys, etc.)
    """
    if not isinstance(schema, ArgumentSchema):
        raise TypeError(f"Expected ArgumentSchema, got {type(schema)}")
    
    _validate_value(args, schema.schema, path="root")


def _validate_value(value: Any, schema_def: Dict[str, Any], path: str = "root") -> None:
    """Recursively validate a value against a schema definition."""
    if not isinstance(schema_def, dict):
        raise ValueError(f"Schema definition at {path} must be a dictionary")
    
    schema_type = schema_def.get("type", "any")
    
    # Handle nullability
    if value is None:
        if schema_def.get("nullable", False):
            return
        raise ValueError(f"Value at {path} is None but schema does not allow null")
    
    if schema_type == "any":
        return
    
    elif schema_type == "dict":
        if not isinstance(value, dict):
            raise TypeError(f"Expected dict at {path}, got {type(value).__name__}")
        
        properties = schema_def.get("properties", {})
        
        # Check required keys
        for key, sub_schema in properties.items():
            is_required = sub_schema.get("required", True) if isinstance(sub_schema, dict) else True
            if is_required and key not in value:
                raise ValueError(f"Missing required key '{key}' at {path}")
        
        # Validate existing keys
        for key, val in value.items():
            if key in properties:
                sub_schema = properties[key]
                if isinstance(sub_schema, dict):
                    _validate_value(val, sub_schema, f"{path}.{key}")
            elif schema_def.get("additionalProperties") is False:
                raise ValueError(f"Unexpected key '{key}' at {path}")
    
    elif schema_type == "list":
        if not isinstance(value, list):
            raise TypeError(f"Expected list at {path}, got {type(value).__name__}")
        
        items_schema = schema_def.get("items", {"type": "any"})
        for i, item in enumerate(value):
            _validate_value(item, items_schema, f"{path}[{i}]")
    
    elif schema_type == "str":
        if not isinstance(value, str):
            raise TypeError(f"Expected str at {path}, got {type(value).__name__}")
    
    elif schema_type == "int":
        # bool is subclass of int in Python, so explicitly exclude it
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"Expected int at {path}, got {type(value).__name__}")
    
    elif schema_type == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"Expected float at {path}, got {type(value).__name__}")
    
    elif schema_type == "bool":
        if not isinstance(value, bool):
            raise TypeError(f"Expected bool at {path}, got {type(value).__name__}")
    
    else:
        raise ValueError(f"Unknown schema type '{schema_type}' at {path}")


def _selftest() -> None:
    """Module-level selftest using temporary SQLite database."""
    import tempfile
    import os
    import inspect
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_argument_schemas.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            # Create tables
            IntPKModel.metadata.create_all(engine)
            
            with Session(engine) as session:
                # 1. Create and persist ArgumentSchema
                nested_schema_def: Dict[str, Any] = {
                    "type": "dict",
                    "properties": {
                        "username": {"type": "str", "required": True},
                        "age": {"type": "int", "required": True},
                        "is_active": {"type": "bool", "required": False},
                        "tags": {
                            "type": "list",
                            "items": {"type": "str"},
                            "required": False
                        },
                        "metadata": {
                            "type": "dict",
                            "properties": {
                                "source": {"type": "str", "required": True},
                                "score": {"type": "float", "required": False}
                            },
                            "required": False
                        }
                    }
                }
                
                schema_v1 = ArgumentSchema(
                    name="user_input",
                    version=1,
                    schema=nested_schema_def
                )
                session.add(schema_v1)
                session.commit()
                
                # Verify persistence
                retrieved = session.execute(
                    select(ArgumentSchema).where(ArgumentSchema.name == "user_input")
                ).scalar_one()
                
                assert retrieved.name == "user_input"
                assert retrieved.version == 1
                assert retrieved.schema == nested_schema_def
                assert isinstance(retrieved.id, int)
                
                # 2. validate_args raises on invalid input (missing required)
                try:
                    validate_args({"age": 25}, retrieved)
                    assert False, "Should have raised for missing username"
                except ValueError as e:
                    assert "username" in str(e)
                
                # 3. validate_args raises on invalid type
                try:
                    validate_args({"username": "alice", "age": "twenty"}, retrieved)
                    assert False, "Should have raised for wrong age type"
                except TypeError as e:
                    assert "int" in str(e)
                
                # 4. validate_args raises on nested invalid type
                try:
                    validate_args({
                        "username": "bob",
                        "age": 30,
                        "metadata": {"source": 123}  # should be str
                    }, retrieved)
                    assert False, "Should have raised for nested type error"
                except TypeError as e:
                    assert "str" in str(e)
                
                # 5. validate_args succeeds with valid nested input
                valid_args = {
                    "username": "charlie",
                    "age": 35,
                    "is_active": True,
                    "tags": ["admin", "user"],
                    "metadata": {
                        "source": "web_form",
                        "score": 95.5
                    }
                }
                validate_args(valid_args, retrieved)  # Should not raise
                
                # 6. Schema versioning - create version 2 with different schema
                schema_v2_def: Dict[str, Any] = {
                    "type": "dict",
                    "properties": {
                        "email": {"type": "str", "required": True},
                        "notification_enabled": {"type": "bool", "required": True}
                    }
                }
                
                schema_v2 = ArgumentSchema(
                    name="user_input",
                    version=2,
                    schema=schema_v2_def
                )
                session.add(schema_v2)
                session.commit()
                
                # Verify versioning respected - retrieve specific version
                v2_record = session.execute(
                    select(ArgumentSchema)
                    .where(ArgumentSchema.name == "user_input")
                    .where(ArgumentSchema.version == 2)
                ).scalar_one()
                
                assert v2_record.version == 2
                assert v2_record.schema == schema_v2_def
                
                # Validate against v2 schema
                validate_args(
                    {"email": "test@example.com", "notification_enabled": False},
                    v2_record
                )
                
                # Ensure v1 schema still works independently
                v1_record = session.execute(
                    select(ArgumentSchema)
                    .where(ArgumentSchema.name == "user_input")
                    .where(ArgumentSchema.version == 1)
                ).scalar_one()
                validate_args(valid_args, v1_record)
                
                # 7. Test type hints are correctly applied
                sig = inspect.signature(validate_args)
                params = sig.parameters
                assert 'args' in params
                assert 'schema' in params
                # Check that schema parameter has type annotation
                assert params['schema'].annotation == ArgumentSchema
                
                # 8. Test list validation
                list_schema = ArgumentSchema(
                    name="list_test",
                    version=1,
                    schema={
                        "type": "list",
                        "items": {"type": "int"}
                    }
                )
                session.add(list_schema)
                session.commit()
                
                validate_args([1, 2, 3], list_schema)
                try:
                    validate_args([1, "two", 3], list_schema)
                    assert False, "Should have raised for list item type"
                except TypeError:
                    pass
                
                logger.info("argument_schemas_validator selftest passed")
                
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
