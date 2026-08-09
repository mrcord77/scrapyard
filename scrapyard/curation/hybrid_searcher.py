"""
hybrid_searcher — Rank database entries using a hybrid of keyword matching and vector similarity

### PART-META-JSON
{
  "name": "hybrid_searcher",
  "layer": "curation",
  "purpose": "Rank database entries using a hybrid of keyword matching and vector similarity",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlite3",
    "urllib.request",
    "json",
    "tempfile",
    "logging",
    "os"
  ],
  "inputs": [
    "need",
    "db_path",
    "keyword_weight",
    "top_k"
  ],
  "outputs": [
    "List[Dict[str, Any]]"
  ],
  "files_created": [
    "sqlite database file (optional)"
  ],
  "security_notes": "Uses urllib to fetch embeddings from localhost; ensure network access is controlled.",
  "ai_usage": "Uses a local embedding API for vector similarity",
  "example": "hybrid_rank('best laptop', 'data.db')",
  "import_path": "scrapyard.curation.hybrid_searcher"
}
### END-PART-META
"""
from typing import List, Dict, Any
import sqlite3
import json
import urllib.request
import logging
import tempfile
import os

STATUS = "core"

def _get_embedding(text: str) -> List[float]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11435/api/embed", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        logging.warning("Embedding service unavailable; using fallback zero vector.")
        return [0.0] * 768

def hybrid_rank(
    need: str,
    db_path: str,
    keyword_weight: float = 0.5,
    top_k: int = 10
) -> List[Dict[str, Any]]:
    """
    Rank database entries using a hybrid of keyword matching and vector similarity.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found at {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Fetch all entries
    cursor.execute("SELECT id, text, vector FROM entries")
    entries = cursor.fetchall()
    conn.close()

    if not entries:
        return []

    # Precompute query embedding
    query_embedding = _get_embedding(need)

    # Process each entry
    results = []
    for entry_id, text, vector_str in entries:
        try:
            vector = json.loads(vector_str)
        except json.JSONDecodeError:
            vector = [0.0] * 768

        # Keyword match score (simple count)
        keyword_score = sum(1 for word in need.split() if word in text.lower())

        # Vector similarity (cosine similarity)
        if sum(vector) == 0 or sum(query_embedding) == 0:
            vector_score = 0.0
        else:
            dot_product = sum(a * b for a, b in zip(vector, query_embedding))
            magnitude = (sum(a**2 for a in vector) ** 0.5) * (sum(b**2 for b in query_embedding) ** 0.5)
            vector_score = dot_product / magnitude if magnitude != 0 else 0.0

        # Hybrid score
        hybrid_score = keyword_score * keyword_weight + vector_score * (1 - keyword_weight)
        results.append({
            "id": entry_id,
            "text": text,
            "keyword_score": keyword_score,
            "vector_score": vector_score,
            "hybrid_score": hybrid_score
        })

    # Sort by hybrid score descending
    results.sort(key=lambda x: x["hybrid_score"], reverse=True)
    return results[:top_k]

def _selftest():
    import os
    import logging
    logging.getLogger().setLevel(logging.CRITICAL)

    # Create a temporary database
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, text TEXT, vector TEXT)")
        cursor.execute("INSERT INTO entries (text, vector) VALUES (?, ?)", ("best laptop", json.dumps([1.0]*768)))
        cursor.execute("INSERT INTO entries (text, vector) VALUES (?, ?)", ("laptop", json.dumps([0.5]*768)))
        cursor.execute("INSERT INTO entries (text, vector) VALUES (?, ?)", ("not relevant", json.dumps([0.0]*768)))
        conn.commit()
        conn.close()

        # Test hybrid_rank
        results = hybrid_rank("best laptop", db_path, keyword_weight=0.5, top_k=2)
        assert len(results) == 2
        assert results[0]["id"] == 1
        assert results[1]["id"] == 2
        assert results[0]["hybrid_score"] > results[1]["hybrid_score"]

        # Test with no entries
        empty_db_path = os.path.join(tmpdir, "empty.db")
        conn = sqlite3.connect(empty_db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, text TEXT, vector TEXT)")
        conn.commit()
        conn.close()
        assert hybrid_rank("test", empty_db_path) == []

        # Test with missing db
        try:
            hybrid_rank("test", "nonexistent.db")
        except FileNotFoundError:
            pass
        else:
            assert False, "Expected FileNotFoundError for nonexistent.db"

    logging.getLogger().setLevel(logging.NOTSET)


if __name__ == "__main__":
    _selftest()
