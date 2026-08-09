"""
source_connector_files — File-based pipeline source connector: reads CSV and JSON files
into validated Pydantic models or type-coerced SQLAlchemy ORM instances.

### PART-META-JSON
{
  "name": "source_connector_files",
  "layer": "data_eng",
  "purpose": "Loads pipeline source data from CSV (DictReader, whitespace-cleaned) and JSON (list-of-objects) files into either Pydantic models (validated, v1/v2 compatible) or SQLAlchemy ORM instances (values coerced to each column's python_type, unknown keys dropped); invalid rows are logged and skipped rather than aborting the load.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "pydantic",
    "sqlalchemy",
    "scrapyard.database.base_model"
  ],
  "inputs": "CSV/JSON file paths plus a schema class (Pydantic BaseModel subclass or SQLAlchemy mapped class).",
  "outputs": "Lists of instantiated schema objects; missing/corrupt files yield an empty list with an error log, never an exception.",
  "files_created": [],
  "security_notes": "Parses untrusted files with stdlib csv/json only (no eval, no pickle) - malformed rows are skipped with a warning that INCLUDES the row content, so route logs handling PII-bearing files accordingly. Bad-file conditions return [] instead of raising; callers must distinguish 'empty source' from 'unreadable source' via logs or a pre-check, or silent data loss results. Type coercion uses each target type's constructor (int('9'), float('1.2')); it never executes row content. File paths are caller-supplied - do not pass user-controlled paths without normalization (traversal).",
  "ai_usage": "read_csv(path, MyModel) / read_json(path, MyModel) where MyModel is a Pydantic or SQLAlchemy schema; check for [] and logs on failure.",
  "example": "from scrapyard.data_eng.source_connector_files import read_csv",
  "import_path": "scrapyard.data_eng.source_connector_files"
}
### END-PART-META
"""
from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Type

from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import (
    Float,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


def _pydantic_validate(schema: Type[PydanticBaseModel], data: Dict[str, Any]) -> PydanticBaseModel:
    if hasattr(schema, "model_validate"):
        return schema.model_validate(data)
    return schema.parse_obj(data)


def _get_sqlalchemy_column_types(schema: Type[Any]) -> Dict[str, Type[Any]]:
    if not hasattr(schema, "__table__"):
        return {}
    type_map: Dict[str, Type[Any]] = {}
    for column in schema.__table__.columns:
        try:
            type_map[column.name] = column.type.python_type
        except NotImplementedError:
            type_map[column.name] = str
    return type_map


def _coerce_value(value: Any, target_type: Type[Any]) -> Any:
    if value is None:
        return None
    if isinstance(value, target_type):
        return value
    if target_type is bool and isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    try:
        return target_type(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Cannot coerce {value!r} to {target_type.__name__}: {exc}"
        ) from exc


def _instantiate_sqlalchemy(schema: Type[Any], data: Dict[str, Any]) -> Any:
    type_map = _get_sqlalchemy_column_types(schema)
    coerced: Dict[str, Any] = {}
    for key, raw in data.items():
        if key not in type_map:
            continue
        coerced[key] = _coerce_value(raw, type_map[key])
    return schema(**coerced)


def read_csv(path: str, schema: Type[PydanticBaseModel]) -> List[PydanticBaseModel]:
    results: List[PydanticBaseModel] = []
    try:
        with open(path, newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                if not row:
                    continue
                cleaned: Dict[str, Any] = {
                    key.strip(): value.strip() if isinstance(value, str) else value
                    for key, value in row.items()
                    if key is not None
                }
                try:
                    if issubclass(schema, PydanticBaseModel):
                        instance = _pydantic_validate(schema, cleaned)
                    else:
                        instance = _instantiate_sqlalchemy(schema, cleaned)
                    results.append(instance)
                except (ValueError, TypeError) as exc:
                    logger.warning(f"Skipping invalid CSV row: {cleaned!r} ({exc})")
    except FileNotFoundError:
        logger.error(f"CSV file not found: {path}")
    except OSError as exc:
        logger.error(f"Failed to read CSV file {path}: {exc}")
    return results


def read_json(path: str, schema: Type[PydanticBaseModel]) -> List[PydanticBaseModel]:
    results: List[PydanticBaseModel] = []
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        logger.error(f"JSON file not found: {path}")
        return results
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to decode JSON file {path}: {exc}")
        return results
    except OSError as exc:
        logger.error(f"Failed to read JSON file {path}: {exc}")
        return results

    if not isinstance(data, list):
        logger.error("JSON root must be a list of objects")
        return results

    for item in data:
        if not isinstance(item, dict):
            logger.warning(f"Skipping non-object JSON item: {item!r}")
            continue
        try:
            if issubclass(schema, PydanticBaseModel):
                instance = _pydantic_validate(schema, item)
            else:
                instance = _instantiate_sqlalchemy(schema, item)
            results.append(instance)
        except (ValueError, TypeError) as exc:
            logger.warning(f"Skipping invalid JSON item: {item!r} ({exc})")
    return results


def _selftest() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        csv_path = os.path.join(temp_dir, "test.csv")
        json_path = os.path.join(temp_dir, "test.json")

        class TestModel(IntPKModel):
            __tablename__ = "test"
            name: Mapped[str] = mapped_column(String(50))
            age: Mapped[int] = mapped_column(Integer)
            score: Mapped[float] = mapped_column(Float)

        with open(csv_path, "w", encoding="utf-8", newline="") as file:
            file.write("name,age,score\nAlice,30,95.5\nBob,25,87.3\nCharlie,35,91.2")

        with open(json_path, "w", encoding="utf-8") as file:
            json.dump(
                [
                    {"name": "David", "age": 40, "score": 89.8},
                    {"name": "Eve", "age": 32, "score": 96.1},
                ],
                file,
            )

        csv_data = read_csv(csv_path, TestModel)
        assert len(csv_data) == 3, "CSV data length mismatch"
        for item in csv_data:
            assert isinstance(item.name, str), f"Name field is not a string: {item.name}"
            assert isinstance(item.age, int), f"Age field is not an integer: {item.age}"
            assert isinstance(item.score, float), f"Score field is not a float: {item.score}"

        json_data = read_json(json_path, TestModel)
        assert len(json_data) == 2, "JSON data length mismatch"
        for item in json_data:
            assert isinstance(item.name, str), f"Name field is not a string: {item.name}"
            assert isinstance(item.age, int), f"Age field is not an integer: {item.age}"
            assert isinstance(item.score, float), f"Score field is not a float: {item.score}"

        engine = create_engine("sqlite:///:memory:", echo=False)
        try:
            TestModel.metadata.create_all(engine)
            with Session(engine) as session:
                for item in csv_data + json_data:
                    session.add(item)
                session.commit()
                count = session.query(TestModel).count()
                assert count == 5, f"Expected 5 rows in SQLite, got {count}"
        finally:
            engine.dispose()

        logger.info("Self-test passed successfully")


if __name__ == "__main__":
    _selftest()
