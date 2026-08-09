"""
data_deduplication — ** The `scrapyard.data_io.data_deduplication` module provides strategies for identifying and resolving duplicate records in datasets, ensuring data integrity during import and export workflows. It sup

### PART-META-JSON
{
  "name": "data_deduplication",
  "layer": "data_io",
  "purpose": "Identifies and resolves duplicate records in list-of-dicts datasets during import/export workflows using pluggable strategy classes with SHA-256 fingerprints over selected keys (keep-first). NOTE: sibling part data_eng/deduplicator covers the pandas-DataFrame case with a pre-dedup Transformer hook - the two are intentionally separate, not duplicates of each other.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Lists of plain-dict records and the unique-key names to fingerprint on; optionally a custom DeduplicationStrategy subclass.",
  "outputs": "New deduplicated record lists (first occurrence per key combination wins); inputs are not mutated.",
  "files_created": [],
  "security_notes": "Pure in-memory processing with stdlib json/hashlib; no network, subprocess, or secret handling. Fingerprints are SHA-256 over canonical JSON of the selected keys - non-JSON-serializable values are stringified via default=str, so two distinct objects with equal str() collide by design; pick unique_keys that are genuinely identifying. Dedup silently DROPS rows; when feeding audit/billing data, record before/after counts. Keep-first means input order decides the surviving record.",
  "ai_usage": "DefaultDeduplicationStrategy(unique_keys=['id']).deduplicate(records); subclass DeduplicationStrategy for custom matching. For DataFrames use scrapyard.data_eng.deduplicator instead.",
  "example": "from scrapyard.data_io.data_deduplication import DefaultDeduplicationStrategy",
  "import_path": "scrapyard.data_io.data_deduplication"
}
### END-PART-META
"""
from typing import Optional, List
import abc
import os
import json
import hashlib
import logging
import sqlite3
import tempfile
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


class DeduplicationStrategy(abc.ABC):
    """Abstract base class for deduplication strategies."""

    unique_keys: List[str] = []

    @abc.abstractmethod
    def deduplicate(self, data: List[dict]) -> List[dict]:
        """Return deduplicated list of records (first occurrence kept)."""
        raise NotImplementedError("Subclasses must implement the deduplicate method")


def _get_fingerprint(record: dict, keys: Optional[List[str]] = None) -> str:
    """Generate a hash fingerprint for a record."""
    if keys:
        # Only hash specified keys
        subset = {k: record.get(k) for k in keys}
    else:
        # Hash entire record
        subset = record
    
    # Use sort_keys for consistent serialization
    canonical = json.dumps(subset, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class DefaultDeduplicationStrategy(DeduplicationStrategy):
    """Default strategy that deduplicates based on specified unique keys."""
    
    unique_keys: List[str] = field(default_factory=lambda: ['id'])
    
    def deduplicate(self, data: List[dict]) -> List[dict]:
        """Return deduplicated data, keeping first occurrence of each unique key combination."""
        if not data:
            return []
        
        seen: set[str] = set()
        unique: List[dict] = []
        
        for item in data:
            fp = _get_fingerprint(item, self.unique_keys)
            if fp not in seen:
                seen.add(fp)
                unique.append(item)
        
        return unique


def find_duplicates(data: List[dict], strategy: Optional[DeduplicationStrategy] = None) -> List[dict]:
    """
    Find duplicate records in the data.
    
    Args:
        data: List of dictionaries to check
        strategy: Optional strategy defining uniqueness criteria
        
    Returns:
        List of records that are duplicates (second and subsequent occurrences)
    """
    if not data:
        return []

    # If no custom strategy is provided, use default
    if strategy is None:
        strategy = DefaultDeduplicationStrategy()

    keys = strategy.unique_keys
    seen: set[str] = set()
    duplicates: List[dict] = []

    for item in data:
        item_hash = _get_fingerprint(item, keys if keys else None)
        if item_hash in seen:
            duplicates.append(item)
        else:
            seen.add(item_hash)

    return duplicates


def _selftest():
    """Self-test suite for the deduplication module."""
    # Sample data
    sample_data = [
        {"id": 1, "name": "Alice", "age": 30},
        {"id": 2, "name": "Bob", "age": 25},
        {"id": 1, "name": "Alice", "age": 30},  # Duplicate
        {"id": 3, "name": "Charlie", "age": 35}
    ]

    # Test find_duplicates with default strategy
    duplicates = find_duplicates(sample_data)
    assert len(duplicates) == 1, f"Expected 1 duplicate, got {len(duplicates)}"
    assert duplicates[0] == {"id": 1, "name": "Alice", "age": 30}, "Duplicate detection failed"

    # Test DeduplicationStrategy subclass
    strategy = DefaultDeduplicationStrategy(unique_keys=['id'])
    deduped = strategy.deduplicate(sample_data)
    assert len(deduped) == 3, f"Expected 3 unique records, got {len(deduped)}"
    assert deduped[0] == {"id": 1, "name": "Alice", "age": 30}
    assert deduped[1] == {"id": 2, "name": "Bob", "age": 25}
    assert deduped[2] == {"id": 3, "name": "Charlie", "age": 35}

    # Create a temporary SQLite database for testing
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    conn = None
    
    try:
        db_path = os.path.join(temp_dir.name, 'test.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create a table and insert sample data
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_table (
                id INTEGER,
                name TEXT,
                age INTEGER
            )
        ''')
        
        for item in sample_data:
            cursor.execute('INSERT INTO test_table (id, name, age) VALUES (?, ?, ?)', 
                           (item['id'], item['name'], item['age']))
        conn.commit()

        # Query the database and find duplicates using window function
        result = cursor.execute('''
            SELECT id, name, age FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY id ORDER BY name) as rn
                FROM test_table
            ) WHERE rn > 1
        ''').fetchall()
        
        assert len(result) == 1, f"Database query for duplicates failed, got {len(result)} rows"
        assert result[0] == (1, 'Alice', 30), f"Unexpected duplicate result: {result[0]}"
        
    finally:
        if conn:
            conn.close()
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
