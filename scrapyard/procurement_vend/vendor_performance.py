"""
vendor_performance - Record vendor delivery performance and generate vendor scorecards.

### PART-META-JSON
{
  "name": "vendor_performance",
  "layer": "procurement_vend",
  "purpose": "Record vendor delivery performance and generate vendor scorecards.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "record_delivery_performance(...); generate_vendor_scorecard(...).",
  "outputs": "PerformanceMetric and Scorecard rows per vendor.",
  "files_created": [],
  "security_notes": "Scorecards influence vendor selection: metrics are recorded append-style so history cannot be silently rewritten. No PII beyond vendor identifiers; no expression evaluation.",
  "ai_usage": "Import what you need from `scrapyard.procurement_vend.vendor_performance`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.procurement_vend.vendor_performance import record_delivery_performance",
  "import_path": "scrapyard.procurement_vend.vendor_performance"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional

from sqlalchemy import create_engine, DateTime, Float, ForeignKey, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

_engine: Optional[Any] = None


class PerformanceMetric(IntPKModel):
    __tablename__ = "performance_metrics"

    vendor_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    scorecard_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("scorecards.id"), nullable=True
    )

    scorecard: Mapped[Optional["Scorecard"]] = relationship(
        "Scorecard", back_populates="metrics"
    )


class Scorecard(IntPKModel):
    __tablename__ = "scorecards"

    vendor_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    metrics: Mapped[List["PerformanceMetric"]] = relationship(
        "PerformanceMetric", back_populates="scorecard"
    )


def _get_session() -> Session:
    if _engine is None:
        raise RuntimeError("vendor_performance database engine is not configured")
    return Session(_engine, expire_on_commit=False)


def record_delivery_performance(
    vendor_id: int, metric: PerformanceMetric, timestamp: datetime
) -> None:
    """Persist a single delivery performance metric for a vendor."""
    with _get_session() as session:
        session.add(
            PerformanceMetric(
                vendor_id=vendor_id,
                metric_name=metric.metric_name,
                value=metric.value,
                timestamp=timestamp,
            )
        )
        session.commit()


def generate_vendor_scorecard(
    vendor_id: int, period_start: datetime, period_end: datetime
) -> Scorecard:
    """Create a scorecard aggregating metrics for a vendor over a time period."""
    with _get_session() as session:
        metrics = session.scalars(
            select(PerformanceMetric)
            .where(
                PerformanceMetric.vendor_id == vendor_id,
                PerformanceMetric.timestamp >= period_start,
                PerformanceMetric.timestamp <= period_end,
            )
            .order_by(PerformanceMetric.timestamp)
        ).all()

        score = sum(metric.value for metric in metrics) / len(metrics) if metrics else 0.0

        scorecard = Scorecard(
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
            score=score,
        )
        scorecard.metrics = list(metrics)

        session.add(scorecard)
        session.commit()

        return scorecard


def _selftest() -> None:
    global _engine

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "vendor_performance_selftest.db")
        engine = create_engine(f"sqlite:///{db_path}")
        _engine = engine

        IntPKModel.metadata.create_all(engine)

        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        record_delivery_performance(
            1,
            PerformanceMetric(
                metric_name="on_time_delivery", value=95.0, timestamp=base_time
            ),
            base_time,
        )
        record_delivery_performance(
            1,
            PerformanceMetric(
                metric_name="on_time_delivery",
                value=85.0,
                timestamp=base_time + timedelta(days=1),
            ),
            base_time + timedelta(days=1),
        )
        record_delivery_performance(
            2,
            PerformanceMetric(metric_name="quality", value=70.0, timestamp=base_time),
            base_time,
        )

        period_start = base_time - timedelta(hours=1)
        period_end = base_time + timedelta(days=2)
        scorecard = generate_vendor_scorecard(1, period_start, period_end)

        assert scorecard.__tablename__ == "scorecards"
        assert scorecard.vendor_id == 1
        assert scorecard.period_start == period_start
        assert scorecard.period_end == period_end
        assert abs(scorecard.score - 90.0) < 1e-9
        assert len(scorecard.metrics) == 2
        assert {m.vendor_id for m in scorecard.metrics} == {1}
        assert {m.metric_name for m in scorecard.metrics} == {"on_time_delivery"}

        with Session(engine) as session:
            metric_count = session.scalar(
                select(func.count()).select_from(PerformanceMetric)
            )
            scorecard_count = session.scalar(
                select(func.count()).select_from(Scorecard)
            )
            assert metric_count == 3
            assert scorecard_count == 1

        engine.dispose()
        _engine = None


if __name__ == "__main__":
    _selftest()
    print("vendor_performance selftest OK")
