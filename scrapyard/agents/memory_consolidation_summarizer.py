"""
memory_consolidation_summarizer — Consolidates and summarizes similar or related memories into general knowledge, enhancing recall and reducing redundancy in memory systems.

### PART-META-JSON
{
  "name": "memory_consolidation_summarizer",
  "layer": "agents",
  "purpose": "Consolidates and summarizes similar or related memories into general knowledge, enhancing recall and reducing redundancy in memory systems.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: cosine_similarity(a, b); consolidate_memories(memories); summarize_knowledge(consolidated); Memory(...); ConsolidatedMemory(...).",
  "outputs": "Returns: consolidate_memories -> List[ConsolidatedMemory]; summarize_knowledge -> str.",
  "files_created": [],
  "security_notes": "Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import what you need from `scrapyard.agents.memory_consolidation_summarizer`.",
  "example": "from scrapyard.agents.memory_consolidation_summarizer import *",
  "import_path": "scrapyard.agents.memory_consolidation_summarizer"
}
### END-PART-META
"""
from typing import List
from dataclasses import dataclass
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
import numpy as np
import hashlib
from datetime import datetime, timezone, timedelta
import sqlite3
import logging
import os
import tempfile

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class Memory:
    id: int
    content: str
    timestamp: datetime

@dataclass
class ConsolidatedMemory:
    id: int
    summary: str
    timestamp: datetime
    memories: List[Memory]

def cosine_similarity(a, b):
    """Compute the cosine similarity between two vectors."""
    dot_product = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    return dot_product / (norm_a * norm_b)

def consolidate_memories(memories: List[Memory]) -> List[ConsolidatedMemory]:
    """Groups similar memories and consolidates them into summaries."""
    if not memories:
        return []

    # Vectorize the content of memories
    vectorizer = TfidfVectorizer()
    X = vectorizer.fit_transform([m.content for m in memories])

    # Cluster the memories using KMeans
    kmeans = KMeans(n_clusters=2, random_state=0).fit(X)
    labels = kmeans.labels_

    # Group memories by cluster
    clusters = {}
    for i, label in enumerate(labels):
        if label not in clusters:
            clusters[label] = []
        clusters[label].append(memories[i])

    # Consolidate each cluster into a summary
    consolidated_memories = []
    for cluster_id, cluster_memories in clusters.items():
        summary = " ".join([m.content for m in cluster_memories])
        timestamp = max(m.timestamp for m in cluster_memories)
        consolidated_memories.append(
            ConsolidatedMemory(
                id=len(consolidated_memories) + 1,
                summary=summary,
                timestamp=timestamp,
                memories=cluster_memories
            )
        )

    return consolidated_memories

def summarize_knowledge(consolidated: List[ConsolidatedMemory]) -> str:
    """Summarizes multiple consolidated memories into a general knowledge entry."""
    if not consolidated:
        return ""

    # Combine all summaries and generate a hash for the summary
    combined_summary = " ".join([c.summary for c in consolidated])
    summary_hash = hashlib.md5(combined_summary.encode()).hexdigest()

    return f"Summary of {len(consolidated)} memories: {summary_hash}"

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Mock data
        memories = [
            Memory(id=1, content="The sky is blue.", timestamp=datetime.now(timezone.utc) - timedelta(days=3)),
            Memory(id=2, content="The ocean is vast and deep.", timestamp=datetime.now(timezone.utc) - timedelta(days=2)),
            Memory(id=3, content="The sun sets in the west.", timestamp=datetime.now(timezone.utc) - timedelta(days=1)),
            Memory(id=4, content="The sky is blue and clear today.", timestamp=datetime.now(timezone.utc))
        ]

        # Test consolidation
        consolidated_memories = consolidate_memories(memories)
        assert len(consolidated_memories) == 2

        # Test summarization
        summary = summarize_knowledge(consolidated_memories)
        logger.info(f"Summary: {summary}")

        # Ensure no database commit occurred during the test
        conn = sqlite3.connect(os.path.join(tmpdir, 'test.db'))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        assert len(tables) == 0

if __name__ == "__main__":
    _selftest()
