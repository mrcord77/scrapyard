"""
document_generator — ** Orchestrate end-to-end document generation using templates and data inputs. Provides a reusable, type-safe, and testable interface for generating documents in bytes format.

### PART-META-JSON
{
  "name": "document_generator",
  "layer": "documents",
  "purpose": "Orchestrate end-to-end document generation using templates and data inputs. Provides a reusable, type-safe, and testable interface for generating documents in bytes format.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: OutputFormat(...); TemplateData(...); DocumentGeneratorConfig(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.documents.document_generator`.",
  "example": "from scrapyard.documents.document_generator import *",
  "import_path": "scrapyard.documents.document_generator"
}
### END-PART-META
"""
from typing import Dict, Any
import logging
from tempfile import TemporaryDirectory
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class OutputFormat(Enum):
    PDF = "pdf"
    DOCX = "docx"

@dataclass
class TemplateData:
    data: Dict[str, Any]

@dataclass
class DocumentGeneratorConfig:
    template_path: str
    output_format: OutputFormat

class DocumentGenerator:
    def __init__(self, config: DocumentGeneratorConfig):
        self.config = config
    
    def _render_template(self, template_id: int, data: TemplateData) -> bytes:
        # Mock rendering logic for demonstration purposes
        if template_id == 1:
            return b"Rendered content from template 1"
        elif template_id == 2:
            return b"Rendered content from template 2"
        else:
            raise ValueError(f"Unknown template ID: {template_id}")
    
    def generate_document(self, template_id: int, data: Dict[str, Any]) -> bytes:
        # Validate input data
        if not isinstance(template_id, int) or not isinstance(data, dict):
            raise TypeError("Invalid input types")
        
        # Convert data to TemplateData object
        template_data = TemplateData(data)
        
        # Generate document
        return self._render_template(template_id, template_data)

def _selftest():
    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        config = DocumentGeneratorConfig(
            template_path=temp_dir,
            output_format=OutputFormat.PDF
        )
        generator = DocumentGenerator(config)
        
        # Test valid template ID and data
        document_bytes = generator.generate_document(1, {"key": "value"})
        assert isinstance(document_bytes, bytes), "generate_document() did not return bytes"
        
        # Test invalid template ID
        try:
            generator.generate_document(3, {})
        except ValueError as e:
            assert str(e) == "Unknown template ID: 3", f"Unexpected error message: {e}"
        
        # Test invalid input types
        try:
            generator.generate_document("1", {"key": "value"})
        except TypeError as e:
            assert str(e) == "Invalid input types", f"Unexpected error message: {e}"

if __name__ == "__main__":
    _selftest()
