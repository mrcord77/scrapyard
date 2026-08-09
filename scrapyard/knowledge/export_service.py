"""
export_service — Exports knowledge base content in structured formats: single articles as genuinely valid single-page PDFs, categories as JSON, and full category bundles as ZIP archives.

### PART-META-JSON
{
  "name": "export_service",
  "layer": "knowledge",
  "purpose": "Exports knowledge base content in structured formats: export_article_to_pdf builds a genuinely valid minimal single-page PDF (hand-constructed header/objects/xref/trailer, no external deps), export_category_to_json returns a category with its articles as a dict, and export_category_to_zip bundles category.json plus one PDF per article into a real ZIP via zipfile. Uses the canonical Category/Article models owned by scrapyard.knowledge.category_service (no models of its own).",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model", "scrapyard.knowledge.category_service"],
  "inputs": "article_id / category_id integers; a session factory bound via _session_factory or the default scrapyard.database.session.",
  "outputs": "PDF bytes, JSON-serializable dicts, ZIP archive bytes; ValueError for missing articles/categories.",
  "files_created": [],
  "security_notes": "No authorization checks: exports return full article content for any id passed in, so enforce read access control in the calling layer before exporting. PDF text is escaped for PDF string syntax and encoded latin-1 with replacement (non-latin characters degrade to '?'); no external renderer is invoked and no HTML/JS can execute. ZIP entries use sanitized fixed-pattern names (article_<id>.pdf), preventing path traversal on extraction.",
  "ai_usage": "Import export functions from `scrapyard.knowledge.export_service`; bind a session factory for testing via the module-level _session_factory.",
  "example": "from scrapyard.knowledge.export_service import export_article_to_pdf, export_category_to_zip",
  "import_path": "scrapyard.knowledge.export_service"
}
### END-PART-META
"""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from typing import Dict, Any, List
import io
import os
import logging
import tempfile
import zipfile

# Canonical-owner pattern: category_service owns the knowledge-layer
# Category/Article models; this part imports them instead of duplicates.
from scrapyard.knowledge.category_service import Article, Category

logger = logging.getLogger(__name__)

# Module-level session factory override for testing
_session_factory = None


def _get_session():
    """Get database session using configured factory or default."""
    if _session_factory is not None:
        return _session_factory()
    from scrapyard.database.session import get_session
    return get_session()


# ---------------------------------------------------------------------------
# Minimal pure-Python PDF writer
# ---------------------------------------------------------------------------

_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_MARGIN = 72
_TITLE_SIZE = 16
_BODY_SIZE = 11
_LINE_HEIGHT = 14
_MAX_LINE_CHARS = 90


def _pdf_escape(text: str) -> str:
    """Escape characters that are special inside PDF literal strings."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap_lines(text: str) -> List[str]:
    """Split text into printable lines, wrapping long ones."""
    lines: List[str] = []
    for raw in text.splitlines() or [""]:
        raw = raw.rstrip()
        if not raw:
            lines.append("")
            continue
        while len(raw) > _MAX_LINE_CHARS:
            cut = raw.rfind(" ", 0, _MAX_LINE_CHARS)
            if cut <= 0:
                cut = _MAX_LINE_CHARS
            lines.append(raw[:cut])
            raw = raw[cut:].lstrip()
        lines.append(raw)
    return lines


def build_minimal_pdf(title: str, body: str) -> bytes:
    """Hand-construct a valid single-page PDF with embedded text streams.

    Produces a complete PDF 1.4 document: %PDF header, catalog/pages/page/
    content-stream/font objects, a correct xref table with byte offsets,
    trailer, startxref, and %%EOF.
    """
    ops = ["BT /F1 %d Tf %d %d Td (%s) Tj ET"
           % (_TITLE_SIZE, _MARGIN, _PAGE_HEIGHT - _MARGIN, _pdf_escape(title))]
    y = _PAGE_HEIGHT - _MARGIN - 2 * _LINE_HEIGHT
    for line in _wrap_lines(body):
        if y < _MARGIN:
            break  # single-page minimal export: truncate overflow
        if line:
            ops.append("BT /F1 %d Tf %d %d Td (%s) Tj ET"
                       % (_BODY_SIZE, _MARGIN, y, _pdf_escape(line)))
        y -= _LINE_HEIGHT
    stream = "\n".join(ops).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
         "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
         % (_PAGE_WIDTH, _PAGE_HEIGHT)).encode("ascii"),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(("%d 0 obj\n" % i).encode("ascii"))
        out.write(obj)
        out.write(b"\nendobj\n")
    xref_pos = out.tell()
    out.write(("xref\n0 %d\n" % (len(objects) + 1)).encode("ascii"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(("%010d 00000 n \n" % off).encode("ascii"))
    out.write(("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n"
               % (len(objects) + 1, xref_pos)).encode("ascii"))
    out.write(b"%%EOF\n")
    return out.getvalue()


def _verify_pdf(data: bytes) -> None:
    """Structural check that *data* parses as a minimal PDF."""
    assert data.startswith(b"%PDF-"), "missing %PDF header"
    assert b"%%EOF" in data[-16:], "missing %%EOF marker"
    assert b"trailer" in data, "missing trailer"
    tail = data[: data.rfind(b"%%EOF")]
    startxref = int(tail[tail.rfind(b"startxref") + len(b"startxref"):].strip())
    assert data[startxref:startxref + 4] == b"xref", "startxref offset does not point at xref table"
    # Every in-use xref entry must point at the start of an "N 0 obj" line.
    xref_lines = data[startxref:].split(b"\n")
    entries = [ln for ln in xref_lines if ln.endswith(b" n ") or ln.endswith(b" n")]
    assert entries, "xref table has no in-use entries"
    for idx, entry in enumerate(entries, start=1):
        off = int(entry.split()[0])
        expected = ("%d 0 obj" % idx).encode("ascii")
        assert data[off:off + len(expected)] == expected, (
            "xref entry %d points at %r, not %r"
            % (idx, data[off:off + len(expected)], expected))


# ---------------------------------------------------------------------------
# Export API
# ---------------------------------------------------------------------------

def export_article_to_pdf(article_id: int) -> bytes:
    """Export an article to a genuinely valid single-page PDF."""
    session: Session = _get_session()
    try:
        article = session.get(Article, article_id)
        if not article:
            raise ValueError(f"Article with ID {article_id} does not exist.")
        return build_minimal_pdf(article.title or "(untitled)", article.content or "")
    finally:
        session.close()


def export_category_to_json(category_id: int) -> Dict[str, Any]:
    """Export a category and its articles to JSON format."""
    session: Session = _get_session()
    try:
        category = session.get(Category, category_id)
        if not category:
            raise ValueError(f"Category with ID {category_id} does not exist.")

        articles = session.execute(
            select(Article).where(Article.category_id == category_id)
        ).scalars().all()

        return {
            "name": category.name,
            "description": category.description,
            "parent_id": category.parent_id,
            "articles": [
                {"id": a.id, "title": a.title, "content": a.content}
                for a in articles
            ],
        }
    finally:
        session.close()


def export_category_to_zip(category_id: int) -> bytes:
    """Export a category bundle as a real ZIP archive.

    The archive contains ``category.json`` (the same structure returned by
    :func:`export_category_to_json`) plus one ``article_<id>.pdf`` per article.
    """
    import json as _json

    data = export_category_to_json(category_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("category.json", _json.dumps(data, indent=2, ensure_ascii=False))
        for art in data["articles"]:
            pdf = build_minimal_pdf(art["title"] or "(untitled)", art["content"] or "")
            zf.writestr("article_%d.pdf" % int(art["id"]), pdf)
    return buf.getvalue()


def _selftest() -> None:
    """Offline self-test suite with temporary SQLite database."""
    global _session_factory

    original_factory = _session_factory

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")

        try:
            from scrapyard.database.base_model import Base
            Base.metadata.create_all(engine)

            TestSession = sessionmaker(bind=engine)
            _session_factory = TestSession

            session = TestSession()
            try:
                category1 = Category(name="Category 1", description="Description for Category 1")
                session.add(category1)
                session.flush()

                article1 = Article(
                    title="Article 1",
                    content="Content of Article 1\nwith (parentheses) and a \\ backslash.",
                    category_id=category1.id,
                )
                article2 = Article(
                    title="Article 2",
                    content="Second article body.",
                    category_id=category1.id,
                )
                session.add_all([article1, article2])
                session.commit()

                cat_id = category1.id
                art_id = article1.id
            finally:
                session.close()

            # PDF export: structurally valid, contains the escaped text.
            pdf_bytes = export_article_to_pdf(art_id)
            assert isinstance(pdf_bytes, bytes) and len(pdf_bytes) > 200
            _verify_pdf(pdf_bytes)
            assert b"Article 1" in pdf_bytes
            assert rb"\(parentheses\)" in pdf_bytes

            # Missing article raises.
            try:
                export_article_to_pdf(99999)
                raise AssertionError("expected ValueError for missing article")
            except ValueError:
                pass

            # JSON export.
            category_data = export_category_to_json(cat_id)
            assert category_data["name"] == "Category 1"
            assert len(category_data["articles"]) == 2
            assert {a["title"] for a in category_data["articles"]} == {"Article 1", "Article 2"}

            # ZIP bundle export: real archive readable by zipfile.
            zip_bytes = export_category_to_zip(cat_id)
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                names = set(zf.namelist())
                assert "category.json" in names
                pdf_names = sorted(n for n in names if n.endswith(".pdf"))
                assert len(pdf_names) == 2
                import json as _json
                loaded = _json.loads(zf.read("category.json").decode("utf-8"))
                assert loaded["name"] == "Category 1"
                for n in pdf_names:
                    _verify_pdf(zf.read(n))
                assert zf.testzip() is None

            logger.info("Self-test passed successfully.")

        finally:
            _session_factory = original_factory
            engine.dispose()


if __name__ == "__main__":
    _selftest()
