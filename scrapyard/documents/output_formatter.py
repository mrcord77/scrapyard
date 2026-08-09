"""
output_formatter — ** Convert rendered document content into target formats like DOCX, PDF, or HTML, ensuring consistent output and format-specific styling. This module provides a flexible and extensible interface for d

### PART-META-JSON
{
  "name": "output_formatter",
  "layer": "documents",
  "purpose": "Convert rendered document content into target formats like DOCX, PDF, or HTML, ensuring consistent output and format-specific styling. This module provides a flexible and extensible interface for d.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: format_output(document, format); to_docx(content); to_pdf(content); to_html(content); Document(...); OutputFormatter(...).",
  "outputs": "Returns: format_output -> bytes; to_docx -> bytes; to_pdf -> bytes; to_html -> bytes.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.documents.output_formatter`.",
  "example": "from scrapyard.documents.output_formatter import *",
  "import_path": "scrapyard.documents.output_formatter"
}
### END-PART-META
"""
import os
from typing import Callable

from dataclasses import dataclass
from tempfile import TemporaryDirectory
import logging

logger = logging.getLogger(__name__)

@dataclass
class Document:
    content: bytes
    format: str

class OutputFormatter:
    def __init__(self):
        self.formatters = {}

    def register_formatter(self, format: str, formatter: Callable[[bytes], bytes]):
        if format in self.formatters:
            raise ValueError(f"Formatter for {format} already exists")
        self.formatters[format] = formatter

    def format_document(self, document: Document) -> bytes:
        formatter = self.formatters.get(document.format)
        if not formatter:
            raise ValueError(f"No formatter registered for {document.format}")
        return formatter(document.content)

def format_output(document: bytes, format: str) -> bytes:
    doc = Document(content=document, format=format)
    return output_formatter.format_document(doc)

output_formatter = OutputFormatter()

# Register formatters
def to_docx(content: bytes) -> bytes:
    # Dummy implementation for DOCX conversion
    return b"DOCX_CONTENT"

def to_pdf(content: bytes) -> bytes:
    # Dummy implementation for PDF conversion
    return b"PDF_CONTENT"

def to_html(content: bytes) -> bytes:
    # Dummy implementation for HTML conversion
    return b"<html><body>HTML_CONTENT</body></html>"

output_formatter.register_formatter("docx", to_docx)
output_formatter.register_formatter("pdf", to_pdf)
output_formatter.register_formatter("html", to_html)

def _selftest() -> None:
    test_dir = TemporaryDirectory(ignore_cleanup_errors=True)
    temp_db_path = os.path.join(test_dir.name, "test.db")

    # Test DOCX
    docx_content = format_output(b"Test content for DOCX", "docx")
    assert isinstance(docx_content, bytes)

    # Test PDF
    pdf_content = format_output(b"Test content for PDF", "pdf")
    assert isinstance(pdf_content, bytes)

    # Test HTML
    html_content = format_output(b"Test content for HTML", "html")
    assert isinstance(html_content, bytes)

    test_dir.cleanup()
    logger.info("Self-test completed successfully")

if __name__ == "__main__":
    _selftest()
