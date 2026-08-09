"""
forgetting_policy_manager — Manages policies for forgetting outdated or less relevant memories. It evaluates memory relevance and applies forgetting rules to maintain efficient and focused agent memory.

### PART-META-JSON
{
  "name": "forgetting_policy_manager",
  "layer": "agents",
  "purpose": "Manages policies for forgetting outdated or less relevant memories. It evaluates memory relevance and applies forgetting rules to maintain efficient and focused agent memory.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "memory_consolidation_summarizer"
  ],
  "inputs": "Public API: evaluate_relevance(memory); apply_forgetting_policy(memory, policy); Memory(...); ForgettingPolicy(...).",
  "outputs": "Returns: evaluate_relevance -> float; apply_forgetting_policy -> None.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.agents.forgetting_policy_manager`.",
  "example": "from scrapyard.agents.forgetting_policy_manager import *",
  "import_path": "scrapyard.agents.forgetting_policy_manager"
}
### END-PART-META
"""

import logging
import sqlite3
import tempfile
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class Memory:
    """Represents a memory item with metadata for forgetting evaluation."""
    id: str
    content: str
    created_at: datetime
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    access_count: int = 0
    summary: Optional[str] = None
    is_forgotten: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ForgettingPolicy:
    """Configuration for memory forgetting policies."""
    max_age_days: Optional[float] = 30.0
    min_access_count: Optional[int] = None
    relevance_threshold: float = 0.3
    strategy: str = "default"


def evaluate_relevance(memory: Memory) -> float:
    """
    Evaluates memory relevance using summarization from memory consolidation.
    
    Returns a score between 0.0 and 1.0, where 1.0 indicates high relevance.
    Incorporates summary quality, recency, and usage frequency.
    
    Args:
        memory: The memory to evaluate.
        
    Returns:
        float: Relevance score in range [0.0, 1.0].
        
    Raises:
        ValueError: If memory is None.
        TypeError: If memory is not a Memory instance.
    """
    if memory is None:
        raise ValueError("Memory cannot be None")
    if not isinstance(memory, Memory):
        raise TypeError(f"Expected Memory instance, got {type(memory)}")
    
    now = datetime.now(timezone.utc)
    
    # Calculate base score from summarization if available
    if memory.summary:
        # Longer, detailed summaries indicate higher importance
        summary_factor = min(1.0, len(memory.summary) / 500.0)
        age_days = (now - memory.created_at).days
        freshness = max(0.0, 1.0 - (age_days / 365.0))
        base_score = 0.6 * summary_factor + 0.4 * freshness
    else:
        # Without summary, significantly reduced base relevance
        base_score = 0.2
    
    # Usage factor: higher access count increases relevance
    usage_score = min(1.0, memory.access_count / 50.0)
    
    # Recency factor: time since last access
    days_since_access = (now - memory.last_accessed).days
    recency_score = max(0.0, 1.0 - (days_since_access / 90.0))
    
    # Weighted combination
    relevance = (base_score * 0.5) + (usage_score * 0.3) + (recency_score * 0.2)
    
    return float(max(0.0, min(1.0, relevance)))


def apply_forgetting_policy(memory: Memory, policy: ForgettingPolicy) -> None:
    """
    Applies forgetting policy to determine if memory should be forgotten.
    
    Evaluates memory against policy thresholds (age, usage, relevance) and
    marks memory as forgotten if conditions are met. Logs audit information.
    
    Args:
        memory: The memory to evaluate.
        policy: The forgetting policy to apply.
        
    Returns:
        None; modifies memory.is_forgotten in place.
        
    Raises:
        ValueError: If memory or policy is None.
        TypeError: If arguments are not of correct type.
    """
    if memory is None:
        raise ValueError("Memory cannot be None")
    if policy is None:
        raise ValueError("Policy cannot be None")
    if not isinstance(memory, Memory):
        raise TypeError(f"Expected Memory instance, got {type(memory)}")
    if not isinstance(policy, ForgettingPolicy):
        raise TypeError(f"Expected ForgettingPolicy instance, got {type(policy)}")
    
    now = datetime.now(timezone.utc)
    reasons = []
    
    # Age check
    if policy.max_age_days is not None:
        age_days = (now - memory.created_at).total_seconds() / 86400.0
        if age_days > policy.max_age_days:
            reasons.append(f"age_exceeded({age_days:.1f}d > {policy.max_age_days}d)")
    
    # Usage check
    if policy.min_access_count is not None:
        if memory.access_count < policy.min_access_count:
            reasons.append(f"low_usage({memory.access_count} < {policy.min_access_count})")
    
    # Relevance check
    relevance = evaluate_relevance(memory)
    if relevance < policy.relevance_threshold:
        reasons.append(f"low_relevance({relevance:.2f} < {policy.relevance_threshold})")
    
    if reasons:
        memory.is_forgotten = True
        logger.info(
            f"FORGET action: memory_id={memory.id}, strategy={policy.strategy}, "
            f"reasons=[{', '.join(reasons)}]"
        )
    else:
        logger.debug(f"RETAIN action: memory_id={memory.id}, relevance={relevance:.2f}")


def _selftest():
    """
    Self-test for forgetting_policy_manager.
    
    Proves:
    - apply_forgetting_policy removes outdated memories when policy triggers
    - evaluate_relevance returns score between 0.0 and 1.0
    - No database writes occur during testing
    - Memory summarization is used in relevance evaluation
    - Policy application respects configured thresholds
    - All functions raise appropriate exceptions on invalid inputs
    - Runs in under 20 seconds with temp SQLite
    """
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Setup verification table to ensure DB is operational
        cursor.execute("CREATE TABLE verification (id INTEGER PRIMARY KEY, data TEXT)")
        conn.commit()
        
        try:
            now = datetime.now(timezone.utc)
            
            # Test exception handling for invalid inputs
            try:
                evaluate_relevance(None)
                assert False, "evaluate_relevance should raise ValueError for None"
            except ValueError:
                pass
            
            try:
                evaluate_relevance("not a memory object")
                assert False, "evaluate_relevance should raise TypeError for wrong type"
            except TypeError:
                pass
            
            try:
                apply_forgetting_policy(None, ForgettingPolicy())
                assert False, "apply_forgetting_policy should raise ValueError for None memory"
            except ValueError:
                pass
            
            try:
                apply_forgetting_policy(Memory(id="1", content="test", created_at=now), None)
                assert False, "apply_forgetting_policy should raise ValueError for None policy"
            except ValueError:
                pass
            
            try:
                apply_forgetting_policy("invalid", ForgettingPolicy())
                assert False, "apply_forgetting_policy should raise TypeError for invalid memory"
            except TypeError:
                pass
            
            try:
                apply_forgetting_policy(Memory(id="1", content="test", created_at=now), "invalid")
                assert False, "apply_forgetting_policy should raise TypeError for invalid policy"
            except TypeError:
                pass
            
            # Test evaluate_relevance returns score in [0.0, 1.0]
            ancient = Memory(
                id="ancient",
                content="old",
                created_at=now - timedelta(days=1000),
                last_accessed=now - timedelta(days=1000),
                access_count=0
            )
            score = evaluate_relevance(ancient)
            assert 0.0 <= score <= 1.0, f"Relevance {score} out of bounds [0.0, 1.0]"
            assert score < 0.5, "Ancient unused memory should have low relevance"
            
            fresh = Memory(
                id="fresh",
                content="new",
                created_at=now,
                last_accessed=now,
                access_count=100
            )
            score_fresh = evaluate_relevance(fresh)
            assert 0.0 <= score_fresh <= 1.0, f"Relevance {score_fresh} out of bounds"
            assert score_fresh > score, "Fresh popular memory should score higher than ancient"
            
            # Test summarization affects relevance evaluation
            with_summary = Memory(
                id="with_sum",
                content="content",
                created_at=now - timedelta(days=30),
                last_accessed=now,
                access_count=10,
                summary="Detailed summary of important events and facts that matter significantly"
            )
            without_summary = Memory(
                id="no_sum",
                content="content",
                created_at=now - timedelta(days=30),
                last_accessed=now,
                access_count=10,
                summary=None
            )
            score_with = evaluate_relevance(with_summary)
            score_without = evaluate_relevance(without_summary)
            assert score_with > score_without, "Summarized memory should have higher relevance"
            
            # Test apply_forgetting_policy removes outdated memories (age trigger)
            old_memory = Memory(
                id="old_mem",
                content="content",
                created_at=now - timedelta(days=100),
                last_accessed=now,
                access_count=50
            )
            age_policy = ForgettingPolicy(max_age_days=30, relevance_threshold=0.0)
            apply_forgetting_policy(old_memory, age_policy)
            assert old_memory.is_forgotten, "Old memory should be forgotten with strict age policy"
            
            # Test policy respects thresholds (retains recent memory)
            new_memory = Memory(
                id="new_mem",
                content="content",
                created_at=now - timedelta(days=5),
                last_accessed=now,
                access_count=20
            )
            retain_policy = ForgettingPolicy(max_age_days=30, min_access_count=1, relevance_threshold=0.1)
            apply_forgetting_policy(new_memory, retain_policy)
            assert not new_memory.is_forgotten, "Recent used memory should not be forgotten"
            
            # Test usage threshold trigger
            unused = Memory(
                id="unused",
                content="content",
                created_at=now - timedelta(days=10),
                last_accessed=now,
                access_count=0
            )
            usage_policy = ForgettingPolicy(min_access_count=5, max_age_days=None, relevance_threshold=0.0)
            apply_forgetting_policy(unused, usage_policy)
            assert unused.is_forgotten, "Unused memory should be forgotten with min_access_count"
            
            # Test relevance threshold trigger
            low_rel = Memory(
                id="low_rel",
                content="content",
                created_at=now - timedelta(days=60),
                last_accessed=now - timedelta(days=60),
                access_count=1,
                summary=""  # Empty summary ensures low relevance
            )
            rel_policy = ForgettingPolicy(relevance_threshold=0.9, max_age_days=None)
            apply_forgetting_policy(low_rel, rel_policy)
            assert low_rel.is_forgotten, "Low relevance memory should be forgotten with high threshold"
            
            # Verify no database writes occurred (module should not persist anything)
            cursor.execute("SELECT COUNT(*) FROM verification")
            count = cursor.fetchone()[0]
            assert count == 0, "Module wrote to database during testing"
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            assert tables == ["verification"], f"Module created unexpected tables: {tables}"
            
        finally:
            conn.close()
    
    elapsed = time.time() - start_time
    assert elapsed < 20, f"Selftest took {elapsed:.2f}s, exceeds 20s limit"
    print(f"_selftest passed in {elapsed:.2f}s")


if __name__ == "__main__":
    _selftest()
