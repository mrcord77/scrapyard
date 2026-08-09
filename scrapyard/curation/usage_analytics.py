"""
scrapyard.curation.usage_analytics
==================================

Lightweight, SQLite-backed usage analytics for scrapyard parts.

Tracks which parts are recommended in each metadata and maintains
per-part counters (with recency decay) to support curation decisions.

### PART-META-JSON
{
  "name": "usage_analytics",
  "layer": "curation",
  "purpose": "SQLite-backed usage analytics for curation: record_metadata logs which parts each metadata recommended; pick_rate/never_used expose decayed per-part counters for ranking and pruning decisions.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "metadata_id + recommended part names.",
  "outputs": "Usage counters in SQLite; pick_rate floats, never_used booleans.",
  "files_created": ["<db_path> sqlite database"],
  "security_notes": "Stores only part names and counts (parameterized SQL, stdlib sqlite3); no user data, no network.",
  "ai_usage": "Call record_metadata after composing; consult pick_rate when breaking ranking ties and never_used when pruning the yard.",
  "example": "from scrapyard.curation.usage_analytics import UsageAnalytics",
  "import_path": "scrapyard.curation.usage_analytics"
}
### END-PART-META
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

DECAY_PER_SECOND = 1e-6  # gentle recency decay constant


class UsageAnalytics:
    """
    SQLite-backed usage analytics.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file. If the parent directory does not
        exist, operations fall back to an in-memory database.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = self._resolve_db_path(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._ensure_tables()

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_db_path(db_path: Optional[str]) -> str:
        if db_path is None or db_path == ":memory:":
            return ":memory:"

        # If the target directory is missing, gracefully fall back to memory.
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent and not os.path.isdir(parent):
            logger.warning(
                "Directory %r missing; falling back to in-memory analytics DB.",
                parent,
            )
            return ":memory:"
        return db_path

    def _ensure_tables(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata_usage (
                    metadata_id TEXT,
                    part TEXT,
                    timestamp REAL,
                    accepted BOOLEAN
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS part_stats (
                    part TEXT PRIMARY KEY,
                    total_recommended INTEGER,
                    total_accepted INTEGER,
                    last_used REAL
                )
                """
            )

    @staticmethod
    def _now() -> float:
        return time.time()

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def record_metadata(self, metadata_id: str, parts: List[str]) -> None:
        """
        Log that ``parts`` were recommended as part of ``metadata_id``.

        This records one row per part in ``metadata_usage`` and increments
        the recommendation counter in ``part_stats``.  Accepted state is
        recorded as ``False`` until an outcome/acceptance update is applied.
        """
        if not metadata_id or parts is None:
            return

        ts = self._now()
        with self._conn:
            for part in parts:
                self._conn.execute(
                    """
                    INSERT INTO metadata_usage (metadata_id, part, timestamp, accepted)
                    VALUES (?, ?, ?, ?)
                    """,
                    (metadata_id, part, ts, False),
                )
                self._conn.execute(
                    """
                    INSERT INTO part_stats (part, total_recommended, total_accepted, last_used)
                    VALUES (?, 1, 0, ?)
                    ON CONFLICT(part) DO UPDATE SET
                        total_recommended = total_recommended + 1,
                        last_used = excluded.last_used
                    """,
                    (part, ts),
                )

    def pick_rate(self, part: str) -> float:
        """
        Return a recency-decayed usage score for ``part``.

        Returns 0.0 for parts that have never been recommended and a
        positive value (capped at 1.0) for parts that have been recommended.
        """
        row = self._conn.execute(
            "SELECT total_recommended, last_used FROM part_stats WHERE part = ?",
            (part,),
        ).fetchone()

        if row is None or row[0] <= 0:
            return 0.0

        total_recommended, last_used = row
        age = max(0.0, self._now() - last_used)
        score = total_recommended * math.exp(-DECAY_PER_SECOND * age)
        return float(min(1.0, score))

    def never_used(self, part: str) -> bool:
        """
        Return ``True`` if ``part`` has never been accepted.
        """
        row = self._conn.execute(
            "SELECT total_accepted FROM part_stats WHERE part = ?",
            (part,),
        ).fetchone()
        return row is None or row[0] == 0

    def close(self) -> None:
        """
        Close the underlying SQLite connection.
        """
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    # ------------------------------------------------------------------ #
    # helpers for external outcome correlation
    # ------------------------------------------------------------------ #
    def _record_acceptance(self, metadata_id: str, part: str) -> None:
        """
        Mark a part as accepted within a specific metadata.

        This is intended for use by outcome correlation workflows such as
        ``outcome_feedback``. It is not part of the public API.
        """
        ts = self._now()
        with self._conn:
            cur = self._conn.execute(
                """
                UPDATE metadata_usage
                SET accepted = ?
                WHERE metadata_id = ? AND part = ? AND accepted = ?
                """,
                (True, metadata_id, part, False),
            )
            if cur.rowcount > 0:
                self._conn.execute(
                    """
                    INSERT INTO part_stats (part, total_recommended, total_accepted, last_used)
                    VALUES (?, 1, 1, ?)
                    ON CONFLICT(part) DO UPDATE SET
                        total_accepted = total_accepted + 1,
                        last_used = excluded.last_used
                    """,
                    (part, ts),
                )

    def __enter__(self) -> "UsageAnalytics":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def _selftest() -> bool:
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Normal on-disk path
        db_path = os.path.join(tmpdir, "usage.db")
        ua = UsageAnalytics(db_path)
        try:
            ua.record_metadata("metadata_1", ["part_a", "part_b"])

            assert ua.pick_rate("part_a") > 0.0, "used part should have pick_rate > 0"
            assert ua.pick_rate("part_b") > 0.0, "used part should have pick_rate > 0"
            assert ua.pick_rate("unused_part") == 0.0, "unused part should have pick_rate 0.0"

            assert ua.never_used("part_a") is True, "recommended but not yet accepted"
            assert ua.never_used("unused_part") is True, "unknown part never accepted"

            # Verify tables and counters directly.
            conn = sqlite3.connect(db_path)
            try:
                metadata_rows = conn.execute(
                    "SELECT metadata_id, part, accepted FROM metadata_usage"
                ).fetchall()
                assert len(metadata_rows) == 2, "two metadata usage rows expected"
                parts = {row[1] for row in metadata_rows}
                assert parts == {"part_a", "part_b"}
                for row in metadata_rows:
                    assert row[2] == 0, "new recommendations are not yet accepted"

                stats = conn.execute(
                    "SELECT part, total_recommended, total_accepted FROM part_stats"
                ).fetchall()
                assert len(stats) == 2, "two part_stats rows expected"
                for part, recommended, accepted in stats:
                    assert recommended == 1, f"{part}: total_recommended should be 1"
                    assert accepted == 0, f"{part}: total_accepted should be 0"
            finally:
                conn.close()

            # Private acceptance helper sanity check
            ua._record_acceptance("metadata_1", "part_a")
            assert ua.never_used("part_a") is False
            assert ua.never_used("part_b") is True

        finally:
            ua.close()

        # Missing parent directory should fall back to memory gracefully.
        bad_path = os.path.join(tmpdir, "missing_dir", "usage.db")
        ua_mem = UsageAnalytics(bad_path)
        try:
            ua_mem.record_metadata("metadata_2", ["part_c"])
            assert ua_mem.pick_rate("part_c") > 0.0, "memory fallback should work"
        finally:
            ua_mem.close()

    logger.info("usage_analytics _selftest passed")
    return True


if __name__ == "__main__":
    _selftest()
