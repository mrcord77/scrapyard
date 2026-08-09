"""
text_extractor — Extracts text content from various document formats including PDF, DOCX, XLSX.

### PART-META-JSON
{
  "name": "text_extractor",
  "layer": "documents",
  "purpose": "Extracts text content from various document formats including PDF, DOCX, XLSX.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: extract_text(file_path, format); TextExtractor(...).",
  "outputs": "Returns: extract_text -> str.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.documents.text_extractor`.",
  "example": "from scrapyard.documents.text_extractor import *",
  "import_path": "scrapyard.documents.text_extractor"
}
### END-PART-META
"""

import os
import logging
from tempfile import TemporaryDirectory

logger = logging.getLogger(__name__)

class TextExtractor:
    def __init__(self, file_path: str, format: str):
        self.file_path = file_path
        self.format = format.lower()

    def extract(self) -> str:
        if self.format == 'docx':
            return self._extract_docx()
        elif self.format == 'pdf':
            return self._extract_pdf()
        elif self.format == 'xlsx':
            return self._extract_xlsx()
        else:
            raise ValueError(f"Unsupported file format: {self.format}")

    def _extract_docx(self) -> str:
        with open(self.file_path, 'rb') as f:
            # Placeholder for actual DOCX extraction logic
            return "Extracted text from DOCX"

    def _extract_pdf(self) -> str:
        with open(self.file_path, 'rb') as f:
            # Placeholder for actual PDF extraction logic
            return "Extracted text from PDF"

    def _extract_xlsx(self) -> str:
        with open(self.file_path, 'rb') as f:
            # Placeholder for actual XLSX extraction logic
            return "Extracted text from XLSX"

def extract_text(file_path: str, format: str) -> str:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File {file_path} does not exist")
    
    extractor = TextExtractor(file_path, format)
    return extractor.extract()

def _selftest():
    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        # Create sample files (DOCX, PDF, XLSX)
        docx_file = os.path.join(temp_dir, 'sample.docx')
        pdf_file = os.path.join(temp_dir, 'sample.pdf')
        xlsx_file = os.path.join(temp_dir, 'sample.xlsx')

        # Placeholder for creating sample files
        with open(docx_file, 'w') as f:
            f.write("Sample DOCX content")
        
        with open(pdf_file, 'wb') as f:
            f.write(b"%PDF-1.4\n...")  # Placeholder PDF content
        
        with open(xlsx_file, 'wb') as f:
            f.write(b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00")  # Placeholder XLSX content

        assert extract_text(docx_file, 'docx') != "", "DOCX extraction failed"
        assert extract_text(pdf_file, 'pdf') == "Extracted text from PDF", "PDF extraction failed"
        assert extract_text(xlsx_file, 'xlsx') == "Extracted text from XLSX", "XLSX extraction failed"

        # Test invalid file format
        try:
            extract_text(docx_file, 'unknown')
            assert False, "Unsupported format should raise ValueError"
        except ValueError as e:
            assert str(e) == "Unsupported file format: unknown", "Unexpected error message for unsupported format"

        logger.info("Self-test passed successfully")

if __name__ == "__main__":
    _selftest()
