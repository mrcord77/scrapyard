"""
memory_recall_scoring — Scores and ranks memories based on relevance to a query, enabling efficient retrieval and prioritization in agent memory systems.

### PART-META-JSON
{
  "name": "memory_recall_scoring",
  "layer": "agents",
  "purpose": "Scores and ranks memories based on relevance to a query, enabling efficient retrieval and prioritization in agent memory systems.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "semantic_memory_index"
  ],
  "inputs": "Public API: cosine_similarity(vec_a, vec_b); score_memory(memory, query); rank_memories(memories, query); Memory(...).",
  "outputs": "Returns: cosine_similarity -> float; score_memory -> float; rank_memories -> List[Tuple[Memory, float]].",
  "files_created": [],
  "security_notes": "Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import what you need from `scrapyard.agents.memory_recall_scoring`.",
  "example": "from scrapyard.agents.memory_recall_scoring import *",
  "import_path": "scrapyard.agents.memory_recall_scoring"
}
### END-PART-META
"""

from dataclasses import dataclass
from typing import List, Tuple, Protocol, Optional, runtime_checkable
import math
import re
import logging
import tempfile
import sqlite3
import hashlib

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"\w+")


@runtime_checkable
class Memory(Protocol):
    """Protocol for memory objects containing vector embeddings."""
    embedding: List[float]


def _generate_embedding(text: str, dimension: int = 128) -> List[float]:
    """
    Generate a deterministic embedding vector for text: a token-level hashed
    term-frequency vector. Words are tokenized, each token is hashed into one
    of `dimension` buckets, bucket counts are accumulated, and the vector is
    L2-normalized. Texts sharing words therefore share buckets, which makes
    cosine similarity between embeddings meaningful (unlike per-character
    hashing, which only measured letter-frequency overlap).
    """
    vector = [0.0] * dimension
    tokens = _TOKEN.findall((text or "").lower())
    if not tokens:
        return vector

    for tok in tokens:
        hash_val = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vector[hash_val % dimension] += 1.0

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vector))
    if norm > 0:
        vector = [x / norm for x in vector]

    return vector


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """
    Compute cosine similarity between two vectors, handling signed values:
    dot(a, b) / (|a| * |b|), which lies in [-1, 1]. Returns 0.0 for zero
    vectors or mismatched dimensions.
    """
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    # Clamp only to absorb floating point error, preserving the sign.
    return max(-1.0, min(1.0, dot_product / (norm_a * norm_b)))


def score_memory(memory: Memory, query: str) -> float:
    """
    Score a memory's relevance to a query using semantic similarity.
    
    Args:
        memory: Memory object with embedding attribute
        query: Query string to compare against
        
    Returns:
        Float score between 0.0 and 1.0
    """
    if not hasattr(memory, 'embedding') or not memory.embedding:
        return 0.0
    
    query_embedding = _generate_embedding(query, dimension=len(memory.embedding))
    score = cosine_similarity(memory.embedding, query_embedding)

    # Relevance is reported in [0, 1]; anti-correlated embeddings score 0.
    return float(max(0.0, score))


def rank_memories(memories: List[Memory], query: str) -> List[Tuple[Memory, float]]:
    """
    Rank memories by relevance to query in descending order.
    
    Args:
        memories: List of memory objects
        query: Query string
        
    Returns:
        List of (memory, score) tuples sorted by descending score
    """
    if not memories:
        return []
    
    scored = [(memory, score_memory(memory, query)) for memory in memories]
    scored.sort(key=lambda x: x[1], reverse=True)
    
    return scored


def _selftest():
    """Module self-test with temporary SQLite and deterministic embeddings."""
    logger.info("Starting memory_recall_scoring selftest")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Verify SQLite functionality
        db_path = f"{tmpdir}/test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE memory_test (id INTEGER PRIMARY KEY, content TEXT)")
        cursor.execute("INSERT INTO memory_test VALUES (1, 'test')")
        conn.commit()
        conn.close()
        
        # Test dataclass implementing Memory protocol
        @dataclass
        class TestMemory:
            id: int
            content: str
            embedding: List[float]
            metadata: Optional[dict] = None
        
        # Create test memories
        memories = [
            TestMemory(1, "python programming language", _generate_embedding("python programming language", 64)),
            TestMemory(2, "machine learning algorithms", _generate_embedding("machine learning algorithms", 64)),
            TestMemory(3, "python data science", _generate_embedding("python data science", 64)),
            TestMemory(4, "cooking italian recipes", _generate_embedding("cooking italian recipes", 64)),
        ]
        
        query = "python coding"
        
        # Test: score_memory returns float between 0 and 1
        for mem in memories:
            score = score_memory(mem, query)
            assert isinstance(score, float), f"Score must be float, got {type(score)}"
            assert 0.0 <= score <= 1.0, f"Score {score} out of bounds"
        
        # Test: rank_memories returns descending sorted list
        ranked = rank_memories(memories, query)
        assert isinstance(ranked, list)
        assert len(ranked) == 4
        
        for i in range(len(ranked) - 1):
            assert ranked[i][1] >= ranked[i+1][1], "Must be sorted descending"
        
        # Test: empty list handling
        empty_ranked = rank_memories([], query)
        assert empty_ranked == [], "Empty list should return empty list"
        
        # Test: consistency
        mem = memories[0]
        s1 = score_memory(mem, query)
        s2 = score_memory(mem, query)
        assert abs(s1 - s2) < 1e-9, "Scoring must be consistent"
        
        # Test: python memories rank higher than cooking
        python_scores = [s for m, s in ranked if "python" in m.content]
        cooking_score = next((s for m, s in ranked if "cooking" in m.content), 0)
        assert max(python_scores) > cooking_score, "Python should score higher"
        
        # Test: empty embedding
        empty_mem = TestMemory(99, "empty", [])
        assert score_memory(empty_mem, query) == 0.0

        # Test: shared tokens actually drive similarity (token-level TF)
        a = _generate_embedding("python programming", 64)
        b = _generate_embedding("python coding", 64)
        c = _generate_embedding("cooking pasta recipes", 64)
        assert cosine_similarity(a, b) > cosine_similarity(a, c), \
            "Shared-token texts must be more similar than disjoint texts"

        # Test: identical text embeds to cosine ~1
        assert abs(cosine_similarity(a, _generate_embedding("python programming", 64)) - 1.0) < 1e-9

        # Test: cosine handles signed values properly
        assert abs(cosine_similarity([1.0, 0.0], [-1.0, 0.0]) - (-1.0)) < 1e-9
        assert cosine_similarity([1.0, 1.0], [1.0, -1.0]) == 0.0
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    logger.info("memory_recall_scoring selftest passed")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
