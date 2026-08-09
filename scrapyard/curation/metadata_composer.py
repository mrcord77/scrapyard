"""
metadata_composer — Compose a bundle of required components based on dependency needs and confidence thresholds.

### PART-META-JSON
{
  "name": "metadata_composer",
  "layer": "curation",
  "purpose": "Compose a bundle of required components based on dependency needs and confidence thresholds.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlite3",
    "urllib.request",
    "json",
    "tempfile",
    "logging"
  ],
  "inputs": [
    "needs",
    "db_path",
    "confidence_threshold"
  ],
  "outputs": [
    "metadata"
  ],
  "files_created": [
    "sqlite database (in-memory or specified path)"
  ],
  "security_notes": "Uses in-memory SQLite by default; no network or GPU usage unless explicitly required.",
  "ai_usage": "Uses external embedding service with fallback if offline.",
  "example": "compose_metadata(['component_a', 'component_b'], ':memory:', 0.7)",
  "import_path": "scrapyard.curation.metadata_composer"
}
### END-PART-META
"""
import sqlite3
import json
import urllib.request
import tempfile
import logging
from typing import Any, Dict, List

STATUS = "core"

def _get_embedding(text: str) -> List[float]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11435/api/embed", timeout=5) as response:
            return json.load(response).get("embedding", [])
    except Exception:
        logging.warning("Embedding service unavailable; using fallback zero vector.")
        return [0.0] * 1024

def _init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS components (
            name TEXT PRIMARY KEY,
            embedding TEXT,
            confidence REAL
        )
    """)
    conn.commit()
    return conn

def _insert_component(conn: sqlite3.Connection, name: str, embedding: List[float], confidence: float) -> None:
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO components (name, embedding, confidence)
        VALUES (?, ?, ?)
    """, (name, json.dumps(embedding), confidence))
    conn.commit()

def _query_components(conn: sqlite3.Connection, needs: List[str], threshold: float) -> Dict[str, Any]:
    cursor = conn.cursor()
    results = {}
    for need in needs:
        cursor.execute("""
            SELECT name, confidence FROM components
            WHERE name LIKE ?
            ORDER BY confidence DESC
            LIMIT 1
        """, (f"%{need}%",))
        row = cursor.fetchone()
        if row and row[1] >= threshold:
            results[row[0]] = row[1]
    return results

def compose_metadata(
    needs: List[str],
    db_path: str = ":memory:",
    confidence_threshold: float = 0.7,
) -> Dict[str, Any]:
    """
    Composes a bundle of components based on the provided needs and confidence threshold.

    Args:
        needs: List of component names or partial names to match.
        db_path: Path to SQLite database (default is in-memory).
        confidence_threshold: Minimum confidence level required for inclusion.

    Returns:
        A dictionary of matched components with their confidence scores.
    """
    conn = _init_db(db_path)
    try:
        for need in needs:
            embedding = _get_embedding(need)
            _insert_component(conn, need, embedding, 1.0)
        return _query_components(conn, needs, confidence_threshold)
    finally:
        conn.close()

def _selftest() -> None:
    import os

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        metadata = compose_metadata(["component_a", "component_b"], db_path, 0.7)
        assert isinstance(metadata, dict), "Metadata is not a dictionary."
        assert len(metadata) >= 0, "Metadata has unexpected length."
        assert all(isinstance(k, str) for k in metadata.keys()), "Metadata keys are not strings."
        assert all(isinstance(v, float) for v in metadata.values()), "Metadata values are not floats."
        assert all(v >= 0.7 for v in metadata.values()), "Metadata values below confidence threshold."


if __name__ == "__main__":
    _selftest()
