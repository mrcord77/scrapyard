"""
chunking — Split documents into overlapping, sentence-aware chunks for retrieval.

### PART-META-JSON
{
  "name": "chunking",
  "layer": "ai",
  "purpose": "Sentence-aware text chunking with overlap for RAG ingestion.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "chunk_text(text, max_chars=1200, overlap=150).",
  "outputs": "List of chunk strings, each <= max_chars, overlapping by ~overlap chars, split on sentence boundaries where possible.",
  "files_created": [],
  "security_notes": "Pure text transformation; no I/O. Overlap preserves context across chunk boundaries so retrieval doesn't lose answers that straddle a split.",
  "ai_usage": "chunks = chunk_text(doc_text); embed and store each.",
  "example": "from scrapyard.ai.chunking import chunk_text; chunk_text('a. b. c.', max_chars=4, overlap=1)",
  "import_path": "scrapyard.ai.chunking"
}
### END-PART-META
"""
from __future__ import annotations

import re
import os
import io
from typing import List, Callable, Any, Iterable, Dict, Optional

STATUS = "core"

_SENT = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 150, sentence_delimiters: str = r"(?<=[.!?])\s+") -> List[str]:
    """Greedy sentence packing up to max_chars, with a trailing-character overlap
    carried into the next chunk so context spanning a boundary is preserved."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    
    overlap = max(0, min(overlap, max_chars - 1))
    sentences = re.split(sentence_delimiters, text)
    chunks: List[str] = []
    cur = ""
    for s in sentences:
        if cur and len(cur) + 1 + len(s) > max_chars:
            chunks.append(cur.strip())
            tail = cur[-overlap:] if overlap else ""
            cur = (tail + " " + s).strip()
        else:
            cur = (cur + " " + s).strip() if cur else s
        # a single sentence longer than max_chars: hard-split it
        while len(cur) > max_chars:
            chunks.append(cur[:max_chars].strip())
            cur = (cur[max_chars - overlap:] if overlap else cur[max_chars:]).strip()
    if cur:
        chunks.append(cur.strip())
    return [c for c in chunks if c]


def chunk_with_metadata(text: str, *, max_chars: int = 1200, overlap: int = 150, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Chunks text and adds metadata to each chunk."""
    chunks = chunk_text(text, max_chars=max_chars, overlap=overlap)
    return [{"chunk": c, **(metadata or {})} for c in chunks]


def chunk_from_file(file_path: str, *, max_chars: int = 1200, overlap: int = 150, sentence_delimiters: str = r"(?<=[.!?])\s+") -> List[str]:
    """Reads text from a file and chunks it."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return chunk_text(f.read(), max_chars=max_chars, overlap=overlap, sentence_delimiters=sentence_delimiters)


def chunk_from_stream(stream: Iterable[str], *, max_chars: int = 1200, overlap: int = 150, sentence_delimiters: str = r"(?<=[.!?])\s+") -> List[str]:
    """Processes text from a stream and chunks it."""
    return chunk_text(''.join(stream), max_chars=max_chars, overlap=overlap, sentence_delimiters=sentence_delimiters)


def chunk_and_serialize(text: str, *, max_chars: int = 1200, overlap: int = 150, serializer: Callable[[str], Any] = lambda x: x) -> List[Any]:
    """Splits text into chunks and applies a user-defined serializer."""
    return [serializer(c) for c in chunk_text(text, max_chars=max_chars, overlap=overlap)]


def chunk_with_audit_hook(text: str, *, max_chars: int = 1200, overlap: int = 150, on_chunk: Optional[Callable[[str, int], None]] = None) -> List[str]:
    """Triggers a hook on each chunk."""
    chunks = []
    for i, c in enumerate(chunk_text(text, max_chars=max_chars, overlap=overlap)):
        if on_chunk:
            on_chunk(c, i)
        chunks.append(c)
    return chunks


def bulk_chunk(texts: List[str], *, max_chars: int = 1200, overlap: int = 150, sentence_delimiters: str = r"(?<=[.!?])\s+") -> List[List[str]]:
    """Processes a list of texts in bulk."""
    return [chunk_text(t, max_chars=max_chars, overlap=overlap, sentence_delimiters=sentence_delimiters) for t in texts]


def _selftest():
    import tempfile

    # trivial cases
    assert chunk_text("") == []
    assert chunk_text("short text.") == ["short text."]

    # sentence-aware packing with overlap; every chunk respects max_chars
    text = "One sentence here. Two sentence here. Three sentence here. Four sentence here."
    chunks = chunk_text(text, max_chars=40, overlap=10)
    assert len(chunks) >= 2
    assert all(len(c) <= 40 for c in chunks)
    # every sentence's content survives somewhere
    joined = " ".join(chunks)
    for word in ("One", "Two", "Three", "Four"):
        assert word in joined

    # hard split of an oversized single sentence
    long_word = "x" * 100
    hard = chunk_text(long_word, max_chars=30, overlap=5)
    assert all(len(c) <= 30 for c in hard)
    assert sum(len(c) for c in hard) >= 100  # nothing lost (overlap adds)

    # metadata attach
    with_meta = chunk_with_metadata("a. b. c.", max_chars=4, overlap=1,
                                    metadata={"doc": "d1"})
    assert with_meta and all(m["doc"] == "d1" and "chunk" in m for m in with_meta)

    # file + stream + bulk + serializer + hook variants
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        p = os.path.join(tmpdir, "t.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        assert chunk_from_file(p, max_chars=40, overlap=10) == chunks

    assert chunk_from_stream(iter([text[:20], text[20:]]), max_chars=40, overlap=10) == chunks
    assert bulk_chunk([text, "tiny."], max_chars=40, overlap=10)[1] == ["tiny."]
    assert chunk_and_serialize("a. b.", max_chars=4, overlap=0,
                               serializer=str.upper) == ["A.", "B."]
    seen = []
    chunk_with_audit_hook(text, max_chars=40, overlap=10,
                          on_chunk=lambda c, i: seen.append(i))
    assert seen == list(range(len(chunks)))

    print("chunking selftest passed")


if __name__ == "__main__":
    _selftest()
