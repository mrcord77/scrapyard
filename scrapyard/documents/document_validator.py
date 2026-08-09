"""
document_validator — Recursive validation of document templates (nested dict/list
structures) with typed errors carrying the exact failure path, plus pluggable
custom rules.

### PART-META-JSON
{
  "name": "document_validator",
  "layer": "documents",
  "purpose": "Validates document templates before rendering: walks nested dicts/lists enforcing string keys and scalar leaf types (str/int/float/bool/datetime), collects every violation as a ValidationError that names the exact path (e.g. template -> user -> age), and supports custom rules via add_rule or subclassing. validate_template gives a boolean facade that logs instead of raising.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Template dicts (arbitrarily nested dicts/lists with scalar leaves); optional rule callables (template, path) that call _add_error on violations.",
  "outputs": "None on success; ValidationError (message + path list) raised by Validator.validate, or bool from validate_template.",
  "files_created": [],
  "security_notes": "Pure in-memory validation; no network, file (outside the selftest temp db), subprocess, or secret handling. Error messages embed template keys and are logged at ERROR level - if templates carry sensitive field names or values appear in custom-rule messages, route these logs accordingly. Recursion depth follows template nesting; pathological deeply-nested input from untrusted sources can hit Python's recursion limit, so cap depth upstream for hostile inputs. Custom rules execute caller code - register only trusted callables.",
  "ai_usage": "validate_template(tpl) for a quick bool; Validator().validate(tpl) to get raised errors with paths; subclass Validator + add_rule for schema-specific checks.",
  "example": "from scrapyard.documents.document_validator import validate_template",
  "import_path": "scrapyard.documents.document_validator"
}
### END-PART-META
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List
import logging
import os
import sqlite3
import tempfile


logger = logging.getLogger(__name__)

Template = Dict[str, Any]


class ValidationError(Exception):
    """Exception raised when a document template fails validation."""

    def __init__(self, message: str, path: List[str]) -> None:
        self.message = message
        self.path = list(path)
        super().__init__(f"{' -> '.join(path)}: {message}")


class Validator:
    """Reusable validator for document templates.

    Subclasses may override validation hooks or register custom rules via
    :meth:`add_rule`.
    """

    def __init__(self) -> None:
        self.errors: List[ValidationError] = []
        self.rules: List[Callable[[Template, List[str]], None]] = []

    def add_rule(self, rule: Callable[[Template, List[str]], None]) -> None:
        """Register a custom template-level validation rule."""
        self.rules.append(rule)

    def validate(self, template: Template) -> None:
        """Validate *template* and raise the first validation error encountered."""
        self.errors.clear()
        if not isinstance(template, dict):
            self._add_error("Template root must be a dictionary", ["template"])
        else:
            self._validate_value(template, ["template"])
            self._run_custom_rules(template)
        if self.errors:
            raise self.errors[0]

    def _run_custom_rules(self, template: Template, path: List[str] | None = None) -> None:
        if path is None:
            path = ["template"]
        for rule in self.rules:
            rule(template, path)

    def _validate_value(self, value: Any, path: List[str]) -> None:
        if isinstance(value, dict):
            for key, sub_value in value.items():
                self._validate_key(key, path)
                self._validate_value(sub_value, [*path, str(key)])
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self._validate_value(item, [*path, str(index)])
        else:
            self._check_type(value, path)

    def _validate_key(self, key: Any, path: List[str]) -> None:
        if not isinstance(key, str):
            self._add_error("Key must be a string", [*path, str(key)])

    def _check_type(self, value: Any, path: List[str]) -> None:
        if isinstance(value, (str, int, float, bool, datetime)):
            return
        self._add_error(
            "Value must be one of string, int, float, bool, or datetime",
            path,
        )

    def _add_error(self, message: str, path: List[str]) -> None:
        error = ValidationError(message, path)
        logger.error("%s at %s", error.message, " -> ".join(path))
        self.errors.append(error)


def validate_template(template: Template) -> bool:
    """Validate a document template against schema and semantic rules.

    Validation errors are logged; this function returns a boolean result rather
    than raising exceptions.
    """
    validator = Validator()
    try:
        validator.validate(template)
    except ValidationError as exc:
        logger.error("Template validation failed: %s", exc.message)
        return False
    return True


def _selftest() -> None:
    """Run a suite of offline tests for the validation framework."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "validation_selftest.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE results (name TEXT PRIMARY KEY, passed INTEGER)")

            # Test cases for validate_template()
            cases = [
                (
                    "validate_template_valid",
                    {"name": "John Doe", "age": 30, "email": "john@example.com"},
                    True,
                ),
                (
                    "validate_template_invalid",
                    {"name": "John Doe", "age": None, "email": "john@example.com"},
                    False,
                ),
                (
                    "validate_template_non_dict",
                    ["not", "a", "dict"],
                    False,
                ),
                (
                    "validate_template_nested_valid",
                    {"user": {"name": "Jane", "tags": ["a", "b"]}},
                    True,
                ),
                (
                    "validate_template_invalid_key",
                    {1: "value"},
                    False,
                ),
            ]

            for name, template, expected in cases:
                result = validate_template(template)
                assert result == expected, f"{name} failed for {template!r}"
                conn.execute(
                    "INSERT INTO results VALUES (?, ?)",
                    (name, int(result == expected)),
                )

            # Validator must raise ValidationError for invalid templates
            validator = Validator()
            raised = False
            try:
                validator.validate({"name": "John Doe", "age": None})
            except ValidationError:
                raised = True
            assert raised is True
            conn.execute(
                "INSERT INTO results VALUES (?, ?)",
                ("validator_raises", int(raised)),
            )

            # Custom rule via subclassing
            class RequiredFieldValidator(Validator):
                def __init__(self, required: List[str]) -> None:
                    super().__init__()
                    self.required = required
                    self.add_rule(self._check_required)

                def _check_required(
                    self, template: Template, path: List[str]
                ) -> None:
                    for field in self.required:
                        if field not in template:
                            self._add_error(
                                f"Missing required field: {field}",
                                [*path, field],
                            )

            custom = RequiredFieldValidator(["title"])
            custom_raised = False
            try:
                custom.validate({"body": "text"})
            except ValidationError:
                custom_raised = True
            assert custom_raised is True
            conn.execute(
                "INSERT INTO results VALUES (?, ?)",
                ("custom_validator", int(custom_raised)),
            )

            conn.commit()
            cursor = conn.execute("SELECT COUNT(*), SUM(passed) FROM results")
            total, passed = cursor.fetchone()
            assert total == 7
            assert passed == 7
        finally:
            conn.close()


if __name__ == "__main__":
    _selftest()
