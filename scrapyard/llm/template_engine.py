"""
template_engine — Prompt template engine: variable and partial substitution, JSON output parsing/repair/validation, and context-keyed example selection backed by the shared ExampleRepository model from few_shot_example_selector.

### PART-META-JSON
{
  "name": "template_engine",
  "layer": "llm",
  "purpose": "Flexible prompt templating for LLM interactions: register_partial()/render_template() substitute reusable partials then variables, parse_output()/repair_json()/validate_json() handle model JSON output, and select_examples(context) pulls context-matched examples from the SAME ExampleRepository table that few_shot_example_selector owns (context maps to its task_type column), eliminating the previous divergent duplicate model.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "few_shot_example_selector",
    "sqlalchemy"
  ],
  "inputs": "register_partial(name, content); render_template(template, variables); configure_engine(engine); add_example(context, content); select_examples(context); parse_output(text); validate_json(data, schema).",
  "outputs": "Rendered template strings; parsed/repaired dicts; example content lists from the shared few_shot_example_selector_example_repository table.",
  "files_created": [],
  "security_notes": "Template rendering is plain string substitution (no eval/exec, no jinja sandbox escape surface) but substituted variables are NOT escaped - do not render untrusted variables into prompts that gate later parsing. repair_json applies heuristics (trailing commas, unquoted keys, quote style) and re-raises when the payload is unrecoverable rather than guessing. Example storage rides few_shot_example_selector's table; access control is whatever you put around that database.",
  "ai_usage": "register_partial('sys', 'You are terse.'); prompt = render_template('{{PARTIAL_sys}} Q: {{q}}', {'q': question}).",
  "example": "from scrapyard.llm.template_engine import render_template",
  "import_path": "scrapyard.llm.template_engine"
}
### END-PART-META
"""

from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from scrapyard.database.base_model import IntPKModel
import re, json, logging, tempfile, os

# Shared example model: few_shot_example_selector owns the richer schema
# (task_type/domain/language/content/template_vars). template_engine's notion of
# "context" maps onto its task_type column, so both parts read and write ONE
# table (few_shot_example_selector_example_repository) instead of two divergent
# models fighting over renamed tables.
from scrapyard.llm.few_shot_example_selector import ExampleRepository

logger = logging.getLogger(__name__)

# Module-level state
_partials: Dict[str, str] = {}
_sqlalchemy_engine: Optional[Any] = None


def configure_engine(engine) -> None:
    """Point the template engine's example selection at a SQLAlchemy engine."""
    global _sqlalchemy_engine
    _sqlalchemy_engine = engine


def add_example(context: str, content: str, **fields: Any) -> None:
    """Store an example for a context in the shared ExampleRepository table
    (context is persisted as the model's task_type)."""
    if _sqlalchemy_engine is None:
        raise RuntimeError("No engine configured. Call configure_engine() first.")
    with Session(_sqlalchemy_engine) as session:
        session.add(ExampleRepository(task_type=context, content=content, **fields))
        session.commit()


def register_partial(name: str, content: str) -> None:
    """Register a partial template for reuse."""
    _partials[name] = content

def render_template(template: str, variables: dict) -> str:
    """Render template with partial substitution followed by variable substitution."""
    result = template
    
    # First pass: replace partials (sorted by length desc to avoid prefix issues)
    for name in sorted(_partials.keys(), key=len, reverse=True):
        content = _partials[name]
        pattern = f'{{{{PARTIAL_{name}}}}}'
        result = result.replace(pattern, content)
    
    # Second pass: replace variables
    for key, value in variables.items():
        pattern = f'{{{{{key}}}}}'
        result = result.replace(pattern, str(value))
    
    return result

def select_examples(context: str) -> List[str]:
    """Select examples for a context from the shared repository (context is the
    shared model's task_type)."""
    if _sqlalchemy_engine is None:
        # Fallback when no database initialized
        return [f"Example {i} for context '{context}'" for i in range(1, 4)]

    with Session(_sqlalchemy_engine) as session:
        # Try exact context match first
        stmt = select(ExampleRepository).where(
            ExampleRepository.task_type == context).limit(3)
        results = session.execute(stmt).scalars().all()

        if not results:
            # Return any available examples up to 3
            stmt = select(ExampleRepository).limit(3)
            results = session.execute(stmt).scalars().all()

        return [r.content for r in results]

def repair_json(text: str) -> Dict[str, Any]:
    """Attempt to repair and parse malformed JSON."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Repair strategies
    repaired = text
    
    # Remove trailing commas before } or ]
    repaired = re.sub(r',(\s*[}\]])', r'\1', repaired)
    
    # Replace single quotes with double quotes for keys and string values (simple heuristic)
    # This is a basic repair - handle unquoted keys by adding quotes
    repaired = re.sub(r'([{,]\s*)(\w+)(\s*:)', r'\1"\2"\3', repaired)
    
    # Fix single-quoted strings to double-quoted (naive approach)
    # Only if not already valid JSON
    if '"' not in repaired and "'" in repaired:
        repaired = repaired.replace("'", '"')
    
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to repair JSON: {e}")
        raise

def parse_output(text: str) -> Dict[str, Any]:
    """Parse JSON output with automatic repair on failure."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return repair_json(text)

def validate_json(data: Dict[str, Any], schema: Dict[str, Any]) -> bool:
    """Validate data against JSON schema (basic implementation supporting type checking)."""
    try:
        # Check null
        if data is None:
            return schema.get("type") == "null"
        
        # Check type
        if "type" in schema:
            schema_type = schema["type"]
            type_map = {
                "object": dict,
                "array": list,
                "string": str,
                "integer": int,
                "number": (int, float),
                "boolean": bool,
                "null": type(None)
            }
            
            if schema_type in type_map:
                expected_type = type_map[schema_type]
                if not isinstance(data, expected_type):
                    # Special case: bool is subclass of int in Python
                    if schema_type == "integer" and isinstance(data, bool):
                        return False
                    if schema_type == "number" and isinstance(data, bool):
                        return False
                    if not isinstance(data, expected_type):
                        return False
        
        # Object validation
        if isinstance(data, dict):
            # Check required fields
            if "required" in schema:
                for field_name in schema["required"]:
                    if field_name not in data:
                        return False
            
            # Check properties
            if "properties" in schema:
                for prop_name, prop_schema in schema["properties"].items():
                    if prop_name in data:
                        if not validate_json(data[prop_name], prop_schema):
                            return False
        
        # Array validation
        if isinstance(data, list) and "items" in schema:
            for item in data:
                if not validate_json(item, schema["items"]):
                    return False
        
        return True
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return False

def _selftest() -> None:
    """Module-level self-test using temporary SQLite database."""
    global _partials, _sqlalchemy_engine
    
    # Reset state
    _partials.clear()
    _sqlalchemy_engine = None
    
    # Fallback path with no engine configured
    fallback = select_examples("anything")
    assert len(fallback) == 3 and all("anything" in ex for ex in fallback)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Initialize database
        db_path = os.path.join(tmpdir, "test_examples.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        configure_engine(engine)

        # Create tables (shared model rides IntPKModel metadata)
        ExampleRepository.metadata.create_all(engine)

        # Verify the model is genuinely SHARED with few_shot_example_selector
        from scrapyard.llm import few_shot_example_selector as fses
        assert ExampleRepository is fses.ExampleRepository
        assert ExampleRepository.__tablename__ == \
            "few_shot_example_selector_example_repository"

        # Populate examples via the context-keyed helper
        for i in range(1, 4):
            add_example("test_context",
                        f"Example {i} for context 'test_context'")

        # The same rows are visible through few_shot_example_selector's API
        fses.configure(engine)
        shared = fses.select_examples("Example context", "test_context")
        assert len(shared) == 3

        # Test register_partial and render_template
        register_partial('header', 'This is a header: {{PARTIAL_header}}')
        rendered = render_template("Welcome to {{PARTIAL_header}}!", {'PARTIAL_header': "Sample Header"})
        expected = "Welcome to This is a header: Sample Header!"
        assert rendered == expected, f"Template rendering failed: expected '{expected}', got '{rendered}'"
        
        # Test select_examples
        examples = select_examples('test_context')
        assert len(examples) == 3, f"Expected 3 examples, got {len(examples)}"
        for example in examples:
            assert 'Example' in example, f"Missing 'Example' in: {example}"
            assert 'test_context' in example, f"Missing 'test_context' in: {example}"
        
        # Test parse_output with valid JSON
        text = '{"key": "value"}'
        parsed_data = parse_output(text)
        assert parsed_data == {'key': 'value'}, f"parse_output failed: {parsed_data}"
        
        # Test repair_json with valid JSON
        text_with_error = '{"key": "value"}'
        repaired_data = repair_json(text_with_error)
        assert repaired_data == {'key': 'value'}, f"repair_json failed: {repaired_data}"
        
        # Test validate_json with valid data
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            },
            "required": ["name", "age"]
        }
        data = {"name": "John Doe", "age": 30}
        assert validate_json(data, schema) is True, "Validation should pass for valid data"
        
        # Test validate_json with invalid data (missing required field)
        invalid_data = {"name": "John Doe"}
        assert validate_json(invalid_data, schema) is False, "Validation should fail for missing required field"
        
        # Test validate_json with wrong type
        wrong_type_data = {"name": "John Doe", "age": "thirty"}
        assert validate_json(wrong_type_data, schema) is False, "Validation should fail for wrong type"
        
        # Cleanup
        fses._engine = None
        engine.dispose()
        _sqlalchemy_engine = None
        _partials.clear()
    
    logger.info("template_engine _selftest passed")

if __name__ == "__main__":
    _selftest()
