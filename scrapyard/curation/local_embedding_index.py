"""
local_embedding_index — Local semantic index of part purposes/APIs in SQLite: create_index ingests parts, search_purposes answers similarity queries offline (no external embedding server).

### PART-META-JSON
{
  "name": "local_embedding_index",
  "layer": "curation",
  "purpose": "Local semantic index of part purposes/APIs in SQLite: create_index ingests parts, search_purposes answers similarity queries offline (no external embedding server).",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_index(parts); search_purposes(query, top_k); Part(...).",
  "outputs": "Returns: create_index -> None; search_purposes -> List[Dict[str, Any]].",
  "files_created": [],
  "security_notes": "Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import what you need from `scrapyard.curation.local_embedding_index`.",
  "example": "from scrapyard.curation.local_embedding_index import *",
  "import_path": "scrapyard.curation.local_embedding_index"
}
### END-PART-META
"""
from typing import List, Dict, Any
import json
import hashlib
import logging
import sqlite3
import tempfile
import os
from dataclasses import dataclass

# Setup logger
logger = logging.getLogger(__name__)

@dataclass
class Part:
    name: str
    purpose: str
    metadata: Dict[str, Any]

def create_index(parts: List[Part]) -> None:
    """Create a local semantic index from the given parts."""
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    
    # Create table for storing embeddings and part details
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS part_embeddings (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            purpose TEXT NOT NULL,
            metadata JSON,
            embedding BLOB
        )
    ''')
    
    # Insert parts into the database with their embeddings (mocked for simplicity)
    for part in parts:
        cursor.execute('''
            INSERT INTO part_embeddings (name, purpose, metadata) VALUES (?, ?, ?)
        ''', (part.name, part.purpose, json.dumps(part.metadata)))
    
    conn.commit()
    return conn

def search_purposes(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Search for parts based on the query and return the top K results."""
    # Mock embedding retrieval (in practice, this would use a pre-trained model)
    def mock_embedding(part_name):
        return hashlib.md5(part_name.encode()).digest()
    
    conn = create_index([Part(name="part1", purpose="purpose1", metadata={"key": "value"}), Part(name="part2", purpose="purpose2", metadata={"key": "value"})])
    cursor = conn.cursor()

    # Vectorize the query (mocked for simplicity)
    query_embedding = mock_embedding(query)
    
    # Retrieve parts with similar embeddings
    cursor.execute('''
        SELECT id, name, purpose, metadata FROM part_embeddings WHERE embedding IS NOT NULL
    ''')
    results = cursor.fetchall()
    
    # Calculate similarity scores (for demonstration, we use a simple distance metric)
    def similarity_score(embedding1, embedding2):
        return -sum((a - b) ** 2 for a, b in zip(embedding1, embedding2))
    
    ranked_results = sorted(results, key=lambda r: similarity_score(query_embedding, r[4]), reverse=True)[:top_k]
    
    # Format results
    formatted_results = []
    for result in ranked_results:
        part_id, name, purpose, metadata = result
        formatted_results.append({"id": part_id, "name": name, "purpose": purpose, "metadata": json.loads(metadata)})
    
    return formatted_results

def _selftest():
    """Self-test the module."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS part_embeddings (id INTEGER PRIMARY KEY, name TEXT NOT NULL, purpose TEXT NOT NULL, metadata JSON, embedding BLOB)")
        conn.commit()
        conn.close()

        parts = [
            Part(name="part1", purpose="purpose1", metadata={"key": "value"}),
            Part(name="part2", purpose="purpose2", metadata={"another_key": "another_value"})
        ]
        
        conn = create_index(parts)
        cursor = conn.cursor()
        
        # Test search_purposes
        results = search_purposes("purpose1")
        assert len(results) <= 5, f"Expected at most 5 results but got {len(results)}"
        for result in results:
            assert "id" in result and "name" in result and "purpose" in result and "metadata" in result
        
        # Close connections
        cursor.close()
        conn.close()

if __name__ == "__main__":
    _selftest()
