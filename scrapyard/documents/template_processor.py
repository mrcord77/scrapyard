"""
template_processor — template processor

### PART-META-JSON
{
  "name": "template_processor",
  "layer": "documents",
  "purpose": "template processor",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: process_template(template, data); TemplateProcessor(...).",
  "outputs": "Returns: process_template -> str.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.documents.template_processor`.",
  "example": "from scrapyard.documents.template_processor import *",
  "import_path": "scrapyard.documents.template_processor"
}
### END-PART-META
"""
from typing import Dict, Any
import re
import time
import logging
import threading
import tempfile
import os

logger = logging.getLogger(__name__)


class TemplateProcessor:
    def __init__(self):
        self.data: Dict[str, Any] = {}
        self.template: str = ""
        self.format: str = "docx"

    def with_data(self, data: Dict[str, Any]) -> 'TemplateProcessor':
        self.data = data
        return self

    def from_string(self, template: str) -> 'TemplateProcessor':
        self.template = template
        return self

    def from_file(self, path: str) -> 'TemplateProcessor':
        with open(path, 'r', encoding='utf-8') as f:
            self.template = f.read()
        return self

    def _resolve_field(self, field_path: str) -> Any:
        keys = field_path.split('.')
        value = self.data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                raise KeyError(field_path)
        return value

    def render(self) -> str:
        if not self.template:
            raise ValueError("Template is not set. Please provide a template.")
        
        logger.info("Starting template rendering")
        
        def replace_match(match):
            field_path = match.group(1).strip()
            value = self._resolve_field(field_path)
            logger.debug(f"Resolved field '{field_path}' to '{value}'")
            return str(value)
        
        pattern = re.compile(r'\{\{\s*([^}]+)\s*\}\}')
        result = pattern.sub(replace_match, self.template)
        
        logger.info("Template rendering completed")
        return result


def process_template(template: str, data: Dict[str, Any]) -> str:
    processor = TemplateProcessor()
    processor.from_string(template).with_data(data)
    return processor.render()


def _selftest():
    logger.info("Starting template processor self-test")
    
    # Test simple merge field replacement
    template = "Hello, {{name}}! You are {{age}} years old."
    data = {"name": "Alice", "age": 30}
    result = process_template(template, data)
    assert result == "Hello, Alice! You are 30 years old.", f"Expected simple replacement, got: {result}"

    # Test nested merge fields
    template = "Name: {{user.name}}, Age: {{user.age}}"
    data = {"user": {"name": "Bob", "age": 25}}
    result = process_template(template, data)
    assert result == "Name: Bob, Age: 25", f"Expected nested replacement, got: {result}"

    # Test error handling for missing merge fields
    template = "Hello, {{unknown_field}}!"
    try:
        process_template(template, {})
        assert False, "Expected KeyError for missing field"
    except KeyError as e:
        assert str(e) == "'unknown_field'", f"Expected KeyError 'unknown_field', got: {str(e)}"

    # Test rendering from string source
    data = {"name": "Charlie", "age": 35}
    result = process_template("Name: {{name}}, Age: {{age}}", data)
    assert result == "Name: Charlie, Age: 35", f"Expected string source render, got: {result}"

    # Test rendering from file source
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        template_path = os.path.join(tmpdir, "template.txt")
        with open(template_path, 'w', encoding='utf-8') as f:
            f.write("Hello, {{name}}! Welcome to {{place}}.")
        
        processor = TemplateProcessor()
        processor.from_file(template_path).with_data({"name": "Dave", "place": "Scrapyard"})
        result = processor.render()
        assert result == "Hello, Dave! Welcome to Scrapyard.", f"Expected file source render, got: {result}"

    # Test thread safety with concurrent template processing
    errors = []
    results = []
    
    def render_template(thread_id):
        try:
            template = "Hello, {{name}}! Thread {{id}}"
            data = {"name": "Test", "id": thread_id}
            result = process_template(template, data)
            expected = f"Hello, Test! Thread {thread_id}"
            if result != expected:
                errors.append(f"Thread {thread_id}: expected {expected}, got {result}")
            results.append(result)
        except Exception as e:
            errors.append(f"Thread {thread_id}: {e}")
    
    threads = []
    thread_count = 10
    start_time = time.time()
    
    for i in range(thread_count):
        t = threading.Thread(target=render_template, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    elapsed_time = time.time() - start_time
    assert not errors, f"Thread safety errors: {errors}"
    assert len(results) == thread_count, f"Expected {thread_count} results, got {len(results)}"
    assert elapsed_time < 2.0, f"Rendering took too long: {elapsed_time}s"

    # Test logging without side effects
    logger.info("Template processing started")
    template = "Hello, {{name}}!"
    data = {"name": "Test"}
    process_template(template, data)
    logger.info("Template processing completed")
    
    logger.info("Template processor self-test completed successfully")


if __name__ == "__main__":
    _selftest()
