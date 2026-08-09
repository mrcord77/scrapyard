"""usage_analytics_collector: collect and store usage analytics for curation parts.

### PART-META-JSON
{
  "name": "usage_analytics_collector",
  "layer": "curation",
  "purpose": "SQLAlchemy-backed usage event collection: collect_usage_data/store_usage persist per-part usage rows with context; UsageStats aggregates counts for curation reporting.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy"],
  "inputs": "part_id, usage context string, SQLAlchemy session.",
  "outputs": "Usage rows (unique per part/context window) and aggregate UsageStats.",
  "files_created": [],
  "security_notes": "Context strings are stored verbatim - keep them to part/task identifiers, never user content or secrets. Parameterized ORM writes only.",
  "ai_usage": "Wire collect_usage_data into the curator's serving path; read UsageStats when tuning rankings.",
  "example": "from scrapyard.curation.usage_analytics_collector import collect_usage_data",
  "import_path": "scrapyard.curation.usage_analytics_collector"
}
### END-PART-META
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# In-memory aggregation buffer for events collected without a database session.
_usage_buffer: Dict[Tuple[int, str], int] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class UsageData:
    part_id: int
    context: str
    count: int = 1
    last_used: datetime = field(default_factory=_utcnow)


class UsageStats(IntPKModel):
    __tablename__ = "usage_stats"

    part_id: Mapped[int] = mapped_column(Integer, nullable=False)
    context: Mapped[str] = mapped_column(String(255), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("part_id", "context", name="uq_usage_stats_part_context"),
        Index("ix_usage_stats_part_id", "part_id"),
        Index("ix_usage_stats_context", "context"),
    )


def _validate_part_id(part_id: Any) -> None:
    if isinstance(part_id, bool) or not isinstance(part_id, int):
        raise TypeError("part_id must be an integer")
    if part_id <= 0:
        raise ValueError("part_id must be a positive integer")


def _validate_context(context: Any) -> None:
    if not isinstance(context, str):
        raise TypeError("context must be a string")
    if not context:
        raise ValueError("context must be a non-empty string")
    if len(context) > 255:
        raise ValueError("context exceeds maximum length of 255 characters")


def collect_usage_data(part_id: int, context: str) -> None:
    """Record a usage event in the in-memory buffer and log it.

    The buffer can later be persisted to the database with :func:`store_usage`.
    """
    _validate_part_id(part_id)
    _validate_context(context)

    key = (part_id, context)
    _usage_buffer[key] = _usage_buffer.get(key, 0) + 1
    logger.info("Usage event collected: part_id=%d context=%r", part_id, context)


def store_usage(session: Session, usage_data: UsageData) -> None:
    """Persist ``usage_data`` to the ``usage_stats`` table.

    If a row for the same ``part_id``/``context`` already exists, its
    ``count`` is incremented by ``usage_data.count`` and ``last_used`` is
    updated.
    """
    if session is None or not isinstance(session, Session):
        raise TypeError("session must be a SQLAlchemy Session")
    if usage_data is None or not isinstance(usage_data, UsageData):
        raise TypeError("usage_data must be a UsageData instance")

    _validate_part_id(usage_data.part_id)
    _validate_context(usage_data.context)

    if isinstance(usage_data.count, bool) or not isinstance(usage_data.count, int):
        raise TypeError("usage_data.count must be an integer")
    if usage_data.count < 0:
        raise ValueError("usage_data.count must be non-negative")

    try:
        stmt = select(UsageStats).where(
            UsageStats.part_id == usage_data.part_id,
            UsageStats.context == usage_data.context,
        )
        existing = session.execute(stmt).scalar_one_or_none()

        if existing is None:
            existing = UsageStats(
                part_id=usage_data.part_id,
                context=usage_data.context,
                count=usage_data.count,
                last_used=usage_data.last_used,
            )
            session.add(existing)
        else:
            existing.count += usage_data.count
            existing.last_used = usage_data.last_used

        session.commit()
        logger.info(
            "Stored usage for part_id=%d context=%r total_count=%d",
            usage_data.part_id,
            usage_data.context,
            existing.count,
        )
    except Exception:
        session.rollback()
        raise


def _get_usage(session: Session, part_id: int, context: str) -> Optional[UsageStats]:
    stmt = select(UsageStats).where(
        UsageStats.part_id == part_id,
        UsageStats.context == context,
    )
    return session.execute(stmt).scalar_one_or_none()


def _reset_buffer() -> None:
    _usage_buffer.clear()


def _selftest() -> None:
    """Offline self-test using a temporary SQLite database."""
    _reset_buffer()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_usage.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        IntPKModel.metadata.create_all(engine)

        # collect_usage_data increments the in-memory usage count.
        collect_usage_data(42, "curation/review")
        collect_usage_data(42, "curation/review")
        collect_usage_data(7, "curation/import")
        assert _usage_buffer[(42, "curation/review")] == 2
        assert _usage_buffer[(7, "curation/import")] == 1

        # store_usage persists data to usage_stats.
        with Session(engine) as session:
            data = UsageData(part_id=42, context="curation/review", count=2)
            store_usage(session, data)
            row = _get_usage(session, 42, "curation/review")
            assert row is not None
            assert row.count == 2
            assert row.context == "curation/review"
            assert row.last_used is not None

        # store_usage increments existing rows.
        with Session(engine) as session:
            data = UsageData(part_id=42, context="curation/review", count=3)
            store_usage(session, data)
            row = _get_usage(session, 42, "curation/review")
            assert row is not None
            assert row.count == 5

        # Invalid inputs raise expected exceptions.
        try:
            collect_usage_data(-1, "context")
            raise AssertionError("Expected ValueError for negative part_id")
        except ValueError:
            pass

        try:
            collect_usage_data(1, "")
            raise AssertionError("Expected ValueError for empty context")
        except ValueError:
            pass

        try:
            collect_usage_data("not-an-int", "context")
            raise AssertionError("Expected TypeError for non-int part_id")
        except TypeError:
            pass

        try:
            collect_usage_data(1, 123)
            raise AssertionError("Expected TypeError for non-str context")
        except TypeError:
            pass

        with Session(engine) as session:
            try:
                store_usage(session, None)
                raise AssertionError("Expected TypeError for None usage_data")
            except TypeError:
                pass

            try:
                store_usage("not-a-session", UsageData(part_id=1, context="ctx"))
                raise AssertionError("Expected TypeError for invalid session")
            except TypeError:
                pass

            try:
                store_usage(
                    session,
                    UsageData(part_id=1, context="ctx", count=-1),
                )
                raise AssertionError("Expected ValueError for negative count")
            except ValueError:
                pass

        engine.dispose()
        _reset_buffer()


if __name__ == "__main__":
    _selftest()
