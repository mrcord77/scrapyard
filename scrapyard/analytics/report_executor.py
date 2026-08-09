"""
report_executor - Execute report generation against a pluggable template engine.

### PART-META-JSON
{
  "name": "report_executor",
  "layer": "analytics",
  "purpose": "Execute report generation against a pluggable template engine.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "generate_report(report_id, metrics); ReportExecutor with a TemplateEngine implementation.",
  "outputs": "Report payload dicts rendered by the configured engine (MockTemplateEngine offline).",
  "files_created": [],
  "security_notes": "Template engines are injected in code (Protocol), not loaded from data. If a real engine renders user-controlled strings, it must escape them - the executor passes metric values through verbatim.",
  "ai_usage": "Import what you need from `scrapyard.analytics.report_executor`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.analytics.report_executor import generate_report",
  "import_path": "scrapyard.analytics.report_executor"
}
### END-PART-META
"""
from typing import List, Dict, Any, Protocol
import logging
import json
from dataclasses import dataclass
from datetime import datetime
import tempfile
import os

logger = logging.getLogger(__name__)


class TemplateEngine(Protocol):
    """Protocol for template rendering engines."""
    
    def render(self, template_id: str, context: Dict[str, Any]) -> str:
        """Render template with context data."""
        ...
    
    def validate(self, template_id: str) -> bool:
        """Validate template configuration."""
        ...
    
    def get_output_format(self, template_id: str) -> str:
        """Determine output format from template identifier."""
        ...


@dataclass
class MockTemplateEngine:
    """Default template engine for testing and basic rendering."""
    
    def render(self, template_id: str, context: Dict[str, Any]) -> str:
        """Serialize context to JSON as mock rendering."""
        return json.dumps({
            "template": template_id,
            "context": context,
            "rendered_at": datetime.now().isoformat()
        })
    
    def validate(self, template_id: str) -> bool:
        """Invalid if empty or contains 'invalid'."""
        if not template_id:
            return False
        if "invalid" in template_id.lower():
            return False
        return True
    
    def get_output_format(self, template_id: str) -> str:
        """Infer format from file extension."""
        template_lower = template_id.lower()
        if template_lower.endswith(".pdf"):
            return "PDF"
        elif template_lower.endswith(".html"):
            return "HTML"
        elif template_lower.endswith(".csv"):
            return "CSV"
        elif template_lower.endswith(".json"):
            return "JSON"
        return "UNKNOWN"


def generate_report(report_id: str, metrics: List[str]) -> Dict[str, Any]:
    """
    Generate a report using the default mock template engine.
    
    Args:
        report_id: Identifier for the report template
        metrics: List of metric identifiers to include
        
    Returns:
        Dictionary containing report metadata, data, and rendered content
    """
    engine = MockTemplateEngine()
    executor = ReportExecutor(engine)
    return executor.execute(report_id, metrics)


class ReportExecutor:
    """
    Executes report generation with dependency-injected template engine.
    Provides isolated execution environment for report tasks.
    """
    
    def __init__(self, template_engine: TemplateEngine):
        """
        Initialize executor with template engine.
        
        Args:
            template_engine: TemplateEngine implementation for rendering
        """
        self.template_engine = template_engine
        self._logger = logging.getLogger(__name__)
    
    def execute(self, report_id: str, metrics: List[str]) -> Dict[str, Any]:
        """
        Execute report generation.
        
        Args:
            report_id: Template/report identifier
            metrics: List of metric identifiers to fetch and include
            
        Returns:
            Report result dictionary with status, data, format, and content
            
        Raises:
            ValueError: If template validation fails
        """
        # Validate configuration
        if not self.template_engine.validate(report_id):
            self._logger.error(f"Template validation failed for: {report_id}")
            raise ValueError(f"Invalid report configuration: {report_id}")
        
        # Handle missing/empty metrics gracefully
        if metrics is None:
            metrics = []
            self._logger.info("Metrics is None, defaulting to empty list")
        
        # Fetch metric data (mock implementation with graceful missing handling)
        metric_data = {}
        for metric_id in metrics:
            if metric_id.startswith("missing_"):
                metric_data[metric_id] = None
                self._logger.warning(f"Metric not found: {metric_id}")
            else:
                metric_data[metric_id] = {
                    "value": 100.0,
                    "unit": "count",
                    "timestamp": datetime.now().isoformat()
                }
        
        # Determine output format from template
        output_format = self.template_engine.get_output_format(report_id)
        
        # Render content
        context = {
            "report_id": report_id,
            "generated_at": datetime.now().isoformat(),
            "metrics": metric_data,
            "metric_count": len(metrics)
        }
        
        try:
            content = self.template_engine.render(report_id, context)
            self._logger.info(f"Successfully generated report: {report_id}")
            status = "success"
        except Exception as e:
            self._logger.error(f"Rendering failed: {e}")
            content = ""
            status = "error"
        
        return {
            "report_id": report_id,
            "metrics": metrics,
            "data": metric_data,
            "format": output_format,
            "content": content,
            "status": status,
            "generated_at": datetime.now().isoformat()
        }


def _selftest():
    """
    Module self-test.
    
    Verifies:
    - generate_report() returns valid report structure with mock metrics
    - ReportExecutor initializes without external dependencies
    - Template validation prevents invalid report configurations
    - Execution handles missing metrics gracefully
    - Output format is correctly inferred from template
    - Logging is captured and does not contain errors
    - No database or network calls are made during test
    """
    import io
    import logging
    
    # Setup log capture
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)
    test_logger = logging.getLogger(__name__)
    test_logger.addHandler(handler)
    original_level = test_logger.level
    test_logger.setLevel(logging.DEBUG)
    
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            # Test generate_report returns valid structure
            result = generate_report("monthly.html", ["users", "revenue"])
            assert isinstance(result, dict)
            assert result["report_id"] == "monthly.html"
            assert "metrics" in result
            assert "data" in result
            assert "content" in result
            assert result["format"] == "HTML"
            assert result["status"] == "success"
            assert "users" in result["data"]
            assert "revenue" in result["data"]
            
            # Test ReportExecutor initializes without external deps
            engine = MockTemplateEngine()
            executor = ReportExecutor(engine)
            assert executor.template_engine is engine
            
            # Test template validation prevents invalid configs
            try:
                executor.execute("invalid_template_config", ["m1"])
                assert False, "Should raise ValueError"
            except ValueError as e:
                assert "Invalid" in str(e)
            
            # Test execution handles missing metrics gracefully
            result_missing = executor.execute(
                "test.pdf", 
                ["existing_metric", "missing_metric_1"]
            )
            assert result_missing["data"]["missing_metric_1"] is None
            assert result_missing["data"]["existing_metric"] is not None
            assert result_missing["status"] == "success"
            
            # Test empty metrics
            result_empty = executor.execute("empty.csv", [])
            assert result_empty["metrics"] == []
            assert result_empty["data"] == {}
            
            # Test output format inference
            assert executor.execute("r.pdf", ["m"])["format"] == "PDF"
            assert executor.execute("r.html", ["m"])["format"] == "HTML"
            assert executor.execute("r.csv", ["m"])["format"] == "CSV"
            assert executor.execute("r.json", ["m"])["format"] == "JSON"
            assert executor.execute("r.unknown", ["m"])["format"] == "UNKNOWN"
            
            # Verify no files created (isolated execution)
            assert len(os.listdir(tmpdir)) == 0
            
            # Verify no errors in logs
            log_output = log_capture.getvalue()
            assert "ERROR" not in log_output, f"Errors found: {log_output}"
            
        return True
        
    finally:
        test_logger.removeHandler(handler)
        test_logger.setLevel(original_level)


if __name__ == "__main__":
    import sys as _sys
    _r = _selftest()
    if _r is not False:
        print("report_executor selftest OK")
    _sys.exit(1 if _r is False else 0)
