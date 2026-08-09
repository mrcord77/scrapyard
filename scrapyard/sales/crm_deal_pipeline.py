"""
crm_deal_pipeline - Track deals through pipeline stages with auditable stage-transition history.

### PART-META-JSON
{
  "name": "crm_deal_pipeline",
  "layer": "sales",
  "purpose": "Track deals through pipeline stages with auditable stage-transition history.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure_database(url); move_deal_to_stage(deal_id, stage_id); get_deal_stage_history(deal_id).",
  "outputs": "Deal / DealStage / DealStageHistoryEntry rows (tables 'crm_deal_pipeline_deal' / 'deal_stage' / 'deal_stage_history'); DealStageHistory dataclasses. Canonical Deal owner - crm_data_export imports this model.",
  "files_created": [],
  "security_notes": "Stage transitions are recorded append-only for audit; moves validate that deal and stage exist. No PII beyond deal titles; no expression evaluation. Actor identity is not captured on transitions - add caller-side audit if attribution is required.",
  "ai_usage": "Import what you need from `scrapyard.sales.crm_deal_pipeline`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.sales.crm_deal_pipeline import configure_database",
  "import_path": "scrapyard.sales.crm_deal_pipeline"
}
### END-PART-META
"""
from __future__ import annotations

"""
PURPOSE
Track deals through various stages of the sales pipeline. Provides a structured way to manage and audit deal progression across stages.

FEATURES
- Track deal movement across stages with audit history
- Support for custom stage definitions
- Efficient querying of deal stage history
- Type-safe ORM models with SQLAlchemy 2.x
- Offline self-test with temporary SQLite
- Full type hints and no runtime side effects
- No network or I/O at import time
- Idempotent move operations with validation
- Scalable for enterprise use with clear separation of concerns

PUBLIC API
def move_deal_to_stage(deal_id: int, stage_id: int) -> None
def get_deal_stage_history(deal_id: int) -> list[DealStageHistory]

TABLES
- deal: stores core deal information
- deal_stage: defines available stages
- deal_stage_history: logs transitions between stages

SELFTEST MUST PROVE
- Creating and moving a deal through multiple stages
- Retrieving full history for a deal
- Validation of invalid stage transitions
- ORM model creation and query
- No runtime errors on cold import
- Correct table structure in SQLite
- Type hints are enforced
- Logging is used instead of print
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine, ForeignKey, Index, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from scrapyard.database.base_model import IntPKModel

import logging
import os
import sqlite3
import tempfile

logger = logging.getLogger(__name__)

_engine: Optional[Any] = None
_SessionFactory: Optional[Any] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Deal(IntPKModel):
    __tablename__ = "crm_deal_pipeline_deal"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    current_stage_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deal_stage.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class DealStage(IntPKModel):
    __tablename__ = "deal_stage"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    stage_order: Mapped[int] = mapped_column(default=0)


class DealStageHistoryEntry(IntPKModel):
    __tablename__ = "deal_stage_history"

    deal_id: Mapped[int] = mapped_column(
        ForeignKey("crm_deal_pipeline_deal.id", ondelete="CASCADE"), nullable=False
    )
    from_stage_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deal_stage.id"), nullable=True
    )
    to_stage_id: Mapped[int] = mapped_column(
        ForeignKey("deal_stage.id"), nullable=False
    )
    transitioned_at: Mapped[datetime] = mapped_column(default=_utcnow)

    __table_args__ = (
        Index("ix_deal_stage_history_deal_id", "deal_id"),
    )


@dataclass(frozen=True)
class DealStageHistory:
    history_id: int
    deal_id: int
    from_stage_id: Optional[int]
    to_stage_id: int
    transitioned_at: datetime


def configure_database(database_url: str) -> None:
    """Configure the module to use the provided database URL.

    Safe to call multiple times; creates tables if they do not exist.
    """
    global _engine, _SessionFactory
    _engine = create_engine(database_url, future=True, echo=False)
    IntPKModel.metadata.create_all(_engine)
    _SessionFactory = sessionmaker(bind=_engine, class_=Session)


def _get_session() -> Session:
    if _SessionFactory is None:
        raise RuntimeError("Database not configured. Call configure_database() first.")
    return _SessionFactory()


def move_deal_to_stage(deal_id: int, stage_id: int) -> None:
    """Move a deal to a new pipeline stage, recording the transition.

    The operation is idempotent: moving a deal to its current stage is a no-op.
    Raises ValueError if the deal or target stage does not exist.
    """
    session = _get_session()
    with session:
        deal = session.get(Deal, deal_id)
        if deal is None:
            raise ValueError(f"Deal {deal_id} does not exist")

        stage = session.get(DealStage, stage_id)
        if stage is None:
            raise ValueError(f"Stage {stage_id} does not exist")

        if deal.current_stage_id == stage_id:
            logger.info(
                "Deal %s is already in stage %s; skipping move", deal_id, stage_id
            )
            return

        history_entry = DealStageHistoryEntry(
            deal_id=deal_id,
            from_stage_id=deal.current_stage_id,
            to_stage_id=stage_id,
        )
        session.add(history_entry)

        deal.current_stage_id = stage_id
        deal.updated_at = _utcnow()

        session.commit()
        logger.info("Moved deal %s to stage %s", deal_id, stage_id)


def get_deal_stage_history(deal_id: int) -> list[DealStageHistory]:
    """Return the full stage transition history for a deal, oldest first."""
    session = _get_session()
    with session:
        entries = session.execute(
            select(DealStageHistoryEntry)
            .where(DealStageHistoryEntry.deal_id == deal_id)
            .order_by(DealStageHistoryEntry.transitioned_at)
        ).scalars().all()

        return [
            DealStageHistory(
                history_id=entry.id,
                deal_id=entry.deal_id,
                from_stage_id=entry.from_stage_id,
                to_stage_id=entry.to_stage_id,
                transitioned_at=entry.transitioned_at,
            )
            for entry in entries
        ]


def _selftest() -> None:
    """Offline self-test using a temporary SQLite database."""
    global _engine, _SessionFactory

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "crm_deal_pipeline_selftest.db")
        configure_database(f"sqlite:///{db_path}")

        seed_session: Session = _get_session()
        with seed_session:
            lead = DealStage(name="lead", stage_order=0)
            qualified = DealStage(name="qualified", stage_order=1)
            closed = DealStage(name="closed", stage_order=2)
            seed_session.add_all([lead, qualified, closed])
            seed_session.commit()

            deal = Deal(title="Self-test Deal", current_stage_id=lead.id)
            seed_session.add(deal)
            seed_session.commit()

            deal_id = deal.id
            lead_id = lead.id
            qualified_id = qualified.id
            closed_id = closed.id

        # Move through multiple stages
        move_deal_to_stage(deal_id, qualified_id)
        move_deal_to_stage(deal_id, closed_id)

        # Idempotent move
        move_deal_to_stage(deal_id, closed_id)

        # Invalid stage transition
        try:
            move_deal_to_stage(deal_id, 999999)
            raise AssertionError("Expected ValueError for non-existent stage")
        except ValueError:
            pass

        # Invalid deal
        try:
            move_deal_to_stage(999999, lead_id)
            raise AssertionError("Expected ValueError for non-existent deal")
        except ValueError:
            pass

        # Retrieve history
        history = get_deal_stage_history(deal_id)
        assert len(history) == 2, f"Expected 2 history entries, got {len(history)}"
        assert history[0].from_stage_id == lead_id
        assert history[0].to_stage_id == qualified_id
        assert history[1].from_stage_id == qualified_id
        assert history[1].to_stage_id == closed_id

        # Verify SQLite table structure
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            # Deal table carries the '<part>_' prefix from the collision rename
            assert "crm_deal_pipeline_deal" in tables
            assert "deal_stage" in tables
            assert "deal_stage_history" in tables

            cursor.execute("PRAGMA table_info(crm_deal_pipeline_deal)")
            deal_columns = {row[1] for row in cursor.fetchall()}
            assert {"id", "title", "current_stage_id", "created_at", "updated_at"} <= deal_columns

            cursor.execute("PRAGMA table_info(deal_stage)")
            stage_columns = {row[1] for row in cursor.fetchall()}
            assert {"id", "name", "stage_order"} <= stage_columns

            cursor.execute("PRAGMA table_info(deal_stage_history)")
            history_columns = {row[1] for row in cursor.fetchall()}
            assert {
                "id",
                "deal_id",
                "from_stage_id",
                "to_stage_id",
                "transitioned_at",
            } <= history_columns

            cursor.execute(
                "SELECT current_stage_id FROM crm_deal_pipeline_deal WHERE id = ?", (deal_id,)
            )
            row = cursor.fetchone()
            assert row is not None and row[0] == closed_id
        finally:
            conn.close()

        # Release pooled connections so the temp directory can be cleaned up
        if _engine is not None:
            _engine.dispose()

        _engine = None
        _SessionFactory = None

        logger.info("_selftest passed")


if __name__ == "__main__":
    _selftest()
    print("crm_deal_pipeline selftest OK")
