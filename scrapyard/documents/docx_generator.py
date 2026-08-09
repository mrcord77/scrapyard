"""
docx_generator — docx generator

### PART-META-JSON
{
  "name": "docx_generator",
  "layer": "documents",
  "purpose": "docx generator",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: render_template(template, data); generate_docx(template_path, data); DocxDocument(...).",
  "outputs": "Returns: render_template -> str; generate_docx -> bytes.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.documents.docx_generator`.",
  "example": "from scrapyard.documents.docx_generator import *",
  "import_path": "scrapyard.documents.docx_generator"
}
### END-PART-META
"""

import io
import os
import zipfile
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# XML templates for minimal DOCX structure
_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>"""

_DOCUMENT_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:r>
        <w:t>{content}</w:t>
      </w:r>
    </w:p>
  </w:body>
</w:document>"""


def _escape_xml(text: Any) -> str:
    """Escape XML special characters."""
    if not isinstance(text, str):
        text = str(text)
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def render_template(template: str, data: Dict[str, Any]) -> str:
    """Render a template string with placeholder substitution.
    
    Args:
        template: Template string containing {{key}} placeholders
        data: Dictionary of values to substitute
        
    Returns:
        Rendered string with placeholders replaced and XML escaped
    """
    result = template
    for key, value in data.items():
        placeholder = f"{{{{{key}}}}}"
        result = result.replace(placeholder, _escape_xml(value))
    return result


class DocxDocument:
    """Represents a DOCX document for generation."""
    
    def __init__(self, template_path: Optional[str] = None):
        """Initialize document with optional template path.
        
        Args:
            template_path: Path to a .docx template file
        """
        self.template_path = template_path
        self._content: Optional[str] = None
    
    def render(self, data: Dict[str, Any]) -> None:
        """Render the document with data.
        
        Args:
            data: Dictionary of values for placeholder substitution
        """
        if self.template_path and os.path.exists(self.template_path):
            with zipfile.ZipFile(self.template_path, 'r') as zf:
                with zf.open('word/document.xml') as f:
                    template_content = f.read().decode('utf-8')
            self._content = render_template(template_content, data)
        else:
            body = data.get("body", str(data))
            self._content = _DOCUMENT_XML_TEMPLATE.format(content=_escape_xml(body))
    
    def generate(self) -> bytes:
        """Generate the DOCX file as bytes.
        
        Returns:
            Bytes containing the DOCX file
        """
        if self._content is None:
            self.render({})
        
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('[Content_Types].xml', _CONTENT_TYPES_XML)
            zf.writestr('_rels/.rels', _RELS_XML)
            zf.writestr('word/_rels/document.xml.rels', _DOC_RELS_XML)
            zf.writestr('word/document.xml', self._content)
        
        buffer.seek(0)
        return buffer.read()
    
    def save(self, path: str) -> None:
        """Save the generated DOCX to a file.
        
        Args:
            path: File path to save to
        """
        data = self.generate()
        with open(path, 'wb') as f:
            f.write(data)


def generate_docx(template_path: str, data: Dict[str, Any]) -> bytes:
    """Generate a DOCX document from a template and data.
    
    Args:
        template_path: Path to the .docx template file
        data: Dictionary of values for placeholder substitution
        
    Returns:
        Bytes containing the generated DOCX file
    """
    doc = DocxDocument(template_path)
    doc.render(data)
    return doc.generate()


def _selftest() -> bool:
    """Run self-contained tests for the module.
    
    Returns:
        True if all tests pass
    """
    import tempfile
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Create a template DOCX file
        template_path = os.path.join(tmpdir, 'template.docx')
        template_xml = _DOCUMENT_XML_TEMPLATE.format(content="Hello {{name}}! Count: {{count}}")
        
        with zipfile.ZipFile(template_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('[Content_Types].xml', _CONTENT_TYPES_XML)
            zf.writestr('_rels/.rels', _RELS_XML)
            zf.writestr('word/_rels/document.xml.rels', _DOC_RELS_XML)
            zf.writestr('word/document.xml', template_xml)
        
        # Test generate_docx
        data = {"name": "World", "count": "42"}
        result = generate_docx(template_path, data)
        
        assert len(result) > 0, "Generated DOCX is empty"
        
        with zipfile.ZipFile(io.BytesIO(result), 'r') as zf:
            assert 'word/document.xml' in zf.namelist()
            with zf.open('word/document.xml') as f:
                content = f.read().decode('utf-8')
                assert 'Hello World!' in content, "Content substitution failed"
                assert 'Count: 42' in content, "Count substitution failed"
                assert '{{name}}' not in content, "Placeholder not replaced"
                assert '{{count}}' not in content, "Placeholder not replaced"
        
        # Test DocxDocument class
        doc = DocxDocument(template_path)
        doc.render({"name": "Test", "count": "99"})
        doc_bytes = doc.generate()
        assert len(doc_bytes) > 0
        
        # Test save
        output_path = os.path.join(tmpdir, 'output.docx')
        doc2 = DocxDocument(template_path)
        doc2.render({"name": "Saved", "count": "1"})
        doc2.save(output_path)
        assert os.path.exists(output_path) and os.path.getsize(output_path) > 0
        
        # Verify saved file
        with zipfile.ZipFile(output_path, 'r') as zf:
            with zf.open('word/document.xml') as f:
                saved = f.read().decode('utf-8')
                assert 'Saved' in saved
        
        # Test render_template directly
        assert render_template("{{a}} and {{b}}", {"a": "A", "b": "B"}) == "A and B"
        assert "&amp;" in render_template("{{x}}", {"x": "A & B"}), "XML escaping failed"
        
        return True


if __name__ == "__main__":
    _selftest()
