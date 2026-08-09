"""
document_diffing — Compare and highlight differences between two documents, providing structured output for review or automation. This module enables precise, efficient document comparison using standard text processing

### PART-META-JSON
{
  "name": "document_diffing",
  "layer": "documents",
  "purpose": "Compare and highlight differences between two documents, providing structured output for review or automation. This module enables precise, efficient document comparison using standard text processing",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: diff_documents(doc1, doc2); DiffResult(...).",
  "outputs": "Returns: diff_documents -> DiffResult.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.documents.document_diffing`.",
  "example": "from scrapyard.documents.document_diffing import *",
  "import_path": "scrapyard.documents.document_diffing"
}
### END-PART-META
"""

import difflib
import logging
import sqlite3
import tempfile
from typing import Any, Dict, List, NamedTuple

logger = logging.getLogger(__name__)


class DiffResult(NamedTuple):
    """Structured result of document comparison.
    
    Attributes:
        changes: List of change dictionaries with 'type' and 'content' keys.
        summary: Dictionary with counts of 'added', 'removed', 'unchanged'.
    """
    changes: List[Dict[str, Any]]
    summary: Dict[str, int]


def diff_documents(doc1: str, doc2: str) -> DiffResult:
    """Compare two documents and return structured diff results.
    
    Performs a line-by-line comparison using difflib to classify
    changes as added, removed, or unchanged. Handles Unicode text
    and preserves line content without modification.
    
    Args:
        doc1: First document content as string.
        doc2: Second document content as string.
        
    Returns:
        DiffResult containing list of changes and summary statistics.
    """
    lines1: List[str] = doc1.splitlines()
    lines2: List[str] = doc2.splitlines()
    
    differ = difflib.Differ()
    diff_lines = list(differ.compare(lines1, lines2))
    
    changes: List[Dict[str, Any]] = []
    summary: Dict[str, int] = {"added": 0, "removed": 0, "unchanged": 0}
    
    for line in diff_lines:
        if line.startswith('+ '):
            changes.append({"type": "added", "content": line[2:]})
            summary["added"] += 1
        elif line.startswith('- '):
            changes.append({"type": "removed", "content": line[2:]})
            summary["removed"] += 1
        elif line.startswith('  '):
            changes.append({"type": "unchanged", "content": line[2:]})
            summary["unchanged"] += 1
        # Skip '? ' lines (intraline change markers from Differ)
    
    return DiffResult(changes=changes, summary=summary)


def _selftest() -> None:
    """Offline self-test suite for document_diffing module."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Test 1: Basic diff returns non-empty result with correct types
        doc1 = "line1\nline2\nline3"
        doc2 = "line1\nline2 modified\nline4"
        result = diff_documents(doc1, doc2)
        
        assert isinstance(result, DiffResult)
        assert len(result.changes) > 0
        types = {c["type"] for c in result.changes}
        assert types.issubset({"added", "removed", "unchanged"})
        
        # Test 2: Summary counts match actual changes
        added_actual = sum(1 for c in result.changes if c["type"] == "added")
        removed_actual = sum(1 for c in result.changes if c["type"] == "removed")
        unchanged_actual = sum(1 for c in result.changes if c["type"] == "unchanged")
        
        assert result.summary["added"] == added_actual
        assert result.summary["removed"] == removed_actual
        assert result.summary["unchanged"] == unchanged_actual
        
        # Test 3: Empty documents produce zero changes
        empty_result = diff_documents("", "")
        assert empty_result.changes == []
        assert empty_result.summary == {"added": 0, "removed": 0, "unchanged": 0}
        
        # Test 4: Non-ASCII characters handled correctly
        unicode_doc1 = "héllo\n日本語\ncafé"
        unicode_doc2 = "héllo\n中文\ncoffee"
        unicode_result = diff_documents(unicode_doc1, unicode_doc2)
        assert isinstance(unicode_result, DiffResult)
        assert len(unicode_result.changes) > 0
        # Verify content is preserved correctly
        for change in unicode_result.changes:
            assert isinstance(change["content"], str)
        
        # Test 5: SQLite integration (verify offline database capability)
        db_path = f"{tmpdir}/test.db"
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE test_diffs (
                    id INTEGER PRIMARY KEY,
                    doc1 TEXT,
                    doc2 TEXT,
                    added INTEGER,
                    removed INTEGER,
                    unchanged INTEGER
                )
            """)
            
            cursor.execute(
                "INSERT INTO test_diffs (doc1, doc2, added, removed, unchanged) VALUES (?, ?, ?, ?, ?)",
                (doc1, doc2, result.summary["added"], 
                 result.summary["removed"], result.summary["unchanged"])
            )
            conn.commit()
            
            cursor.execute("SELECT added, removed, unchanged FROM test_diffs WHERE id=1")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == result.summary["added"]
            assert row[1] == result.summary["removed"]
            assert row[2] == result.summary["unchanged"]
        finally:
            conn.close()
        
        logger.info("document_diffing self-test passed")


if __name__ == "__main__":
    _selftest()
