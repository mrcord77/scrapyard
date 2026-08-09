"""
pdf_reader — Lightweight, lazy-loading PDF text and metadata extraction (pypdf with
PyPDF2 fallback), returning one typed PDFPage (text, page_number, metadata) per page.

### PART-META-JSON
{
  "name": "pdf_reader",
  "layer": "documents",
  "purpose": "Extracts text and document metadata from PDF files via pypdf (falling back to the legacy PyPDF2 API if only that is installed), returning an ordered list of PDFPage dataclasses with per-page text, 1-based page numbers, and the document info dict; extraction failures are logged with the page number and re-raised rather than silently returning partial data.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "pypdf (or PyPDF2 as fallback; imported lazily)"
  ],
  "inputs": "Path to a PDF file.",
  "outputs": "List[PDFPage] with text (str, may be empty for image-only pages), page_number (int, 1-based), metadata (dict copied per page).",
  "files_created": [],
  "security_notes": "PDF parsing is a serious attack surface: hostile PDFs can exploit parser bugs, embed decompression bombs, or carry huge object graphs - keep pypdf patched and impose file-size/page-count limits upstream before parsing untrusted uploads. This module extracts text only; it never executes embedded JavaScript, follows launch actions, or fetches external references. Extracted text and metadata are attacker-controlled strings when the source is untrusted - sanitize before rendering into HTML or shell commands. No network or secret handling.",
  "ai_usage": "pages = read_pdf(path); iterate pages for .text/.page_number/.metadata. Empty .text usually means a scanned page - route those to documents/ocr_integration.",
  "example": "from scrapyard.documents.pdf_reader import read_pdf",
  "import_path": "scrapyard.documents.pdf_reader"
}
### END-PART-META
"""

import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class PDFPage:
    """A single page extracted from a PDF document."""

    text: str
    page_number: int
    metadata: Dict[str, Any] = field(default_factory=dict)


def _pdf_backend_available() -> bool:
    """True if a PDF parsing backend (pypdf, or legacy PyPDF2) is importable."""
    try:
        import pypdf  # noqa: F401
        return True
    except ImportError:
        try:
            import PyPDF2  # noqa: F401
            return True
        except ImportError:
            return False


def read_pdf(file_path: str) -> List[PDFPage]:
    """
    Extract text and metadata from a PDF file.

    Parameters
    ----------
    file_path: str
        Path to the PDF file to read.

    Returns
    -------
    List[PDFPage]
        One ``PDFPage`` per page in the document, in order.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # legacy fallback
        except Exception:
            logger.exception("Neither pypdf nor PyPDF2 is installed for read_pdf")
            raise

    pages: List[PDFPage] = []

    try:
        with open(file_path, "rb") as pdf_file:
            reader = PdfReader(pdf_file)

            doc_metadata: Dict[str, Any] = {}
            if reader.metadata is not None:
                try:
                    doc_metadata = {
                        str(key): reader.metadata[key]
                        for key in reader.metadata
                    }
                except Exception:
                    logger.warning(
                        "Could not convert PDF metadata to dict; using empty metadata"
                    )
                    doc_metadata = {}

            for index, raw_page in enumerate(reader.pages, start=1):
                try:
                    extracted_text = raw_page.extract_text() or ""
                except Exception:
                    logger.exception(
                        "Text extraction failed for page %s of %s", index, file_path
                    )
                    raise

                pages.append(
                    PDFPage(
                        text=extracted_text,
                        page_number=index,
                        metadata=dict(doc_metadata),
                    )
                )
    except Exception:
        logger.exception("Failed to read PDF: %s", file_path)
        raise

    return pages


def _make_sample_pdf_bytes() -> bytes:
    """
    Build a minimal, valid PDF in memory.

    The generated document contains a single page with the text
    ``Hello, PDF Reader!``.
    """
    content_stream = b"BT /F1 12 Tf 100 700 Td (Hello, PDF Reader!) Tj ET"

    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        (
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
            b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>"
        ),
        (
            b"<</Length " + str(len(content_stream)).encode() + b">>\nstream\n"
            + content_stream
            + b"\nendstream"
        ),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]

    body = bytearray(b"%PDF-1.4\n")
    offsets: List[int] = []

    for obj_number, obj_data in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{obj_number} 0 obj\n".encode())
        body.extend(obj_data)
        body.extend(b"\nendobj\n")

    xref_offset = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    body.extend(b"0000000000 65535 f \n")

    for offset in offsets:
        body.extend(f"{offset:010d} 00000 n \n".encode())

    body.extend(b"trailer\n<</Size ")
    body.extend(str(len(objects) + 1).encode())
    body.extend(b"/Root 1 0 R>>\n")
    body.extend(b"startxref\n")
    body.extend(str(xref_offset).encode())
    body.extend(b"\n%%EOF\n")

    return bytes(body)


def _selftest() -> None:
    """
    Offline self-test for the PDF reader module.

    Proves that ``read_pdf`` can parse a sample PDF stored in an in-memory
    SQLite database into ``PDFPage`` objects with non-empty text.
    """
    if not _pdf_backend_available():
        print("pdf_reader selftest: SKIPPED (neither pypdf nor PyPDF2 installed)")
        return

    connection = sqlite3.connect(":memory:")
    try:
        cursor = connection.cursor()
        cursor.execute(
            "CREATE TABLE pdf_store (id INTEGER PRIMARY KEY, data BLOB)"
        )

        sample_pdf = _make_sample_pdf_bytes()
        cursor.execute(
            "INSERT INTO pdf_store (data) VALUES (?)",
            (sample_pdf,),
        )
        connection.commit()

        cursor.execute("SELECT data FROM pdf_store WHERE id = 1")
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Sample PDF row not found in in-memory database")

        pdf_bytes = row[0]

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            pdf_path = os.path.join(tmpdir, "sample.pdf")
            with open(pdf_path, "wb") as pdf_file:
                pdf_file.write(pdf_bytes)

            pages = read_pdf(pdf_path)

        assert isinstance(pages, list), "read_pdf must return a list"
        assert len(pages) > 0, "sample PDF must contain at least one page"

        for page in pages:
            assert isinstance(page, PDFPage), "each item must be a PDFPage"
            assert isinstance(page.text, str), "page text must be a string"
            assert page.text.strip(), "page text must be non-empty"
            assert isinstance(page.metadata, dict), "page metadata must be a dict"

        logger.info(
            "scrapyard.documents.pdf_reader _selftest passed: "
            "extracted %d page(s)",
            len(pages),
        )
    except Exception:
        logger.exception("scrapyard.documents.pdf_reader _selftest failed")
        raise
    finally:
        connection.close()

    print("pdf_reader selftest: all tests passed")


if __name__ == "__main__":
    _selftest()
