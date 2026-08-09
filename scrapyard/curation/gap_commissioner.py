"""
gap_commissioner — Record needs the catalog could not satisfy well, so missing parts get commissioned instead of forgotten.

### PART-META-JSON
{
  "name": "gap_commissioner",
  "layer": "curation",
  "purpose": "Track curation gaps: record_gap stores (need, best part, score) rows; prioritize_gaps surfaces the worst-served needs below a score threshold; list_unmet_needs feeds the build queue.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy"],
  "inputs": "db_path, need text, best-matching part name, match score.",
  "outputs": "Gap rows in SQLite; prioritized gap lists.",
  "files_created": ["<db_path> sqlite database"],
  "security_notes": "Stores caller-supplied need text verbatim in SQLite (parameterized writes); no network, no code execution. Need text may reveal roadmap intent - keep the gap db internal.",
  "ai_usage": "After a low-scoring search, record_gap(db, need, part, score); periodically prioritize_gaps(db) to decide what to scaffold next.",
  "example": "from scrapyard.curation.gap_commissioner import record_gap, prioritize_gaps",
  "import_path": "scrapyard.curation.gap_commissioner"
}
### END-PART-META
"""
from sqlalchemy import create_engine, select, delete, String, Float, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from typing import List, Dict, Any
import os
import logging

logger = logging.getLogger(__name__)


class Gap(IntPKModel):
    __tablename__ = "curation_gap"

    need: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    part: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("need", "part", name="uq_curation_gap_need_part"),
    )


def _engine(db_path: str):
    engine = create_engine(
        f"sqlite:///{os.path.abspath(db_path)}",
        future=True,
        echo=False,
    )
    IntPKModel.metadata.create_all(engine)
    return engine


def record_gap(db_path: str, need: str, part: str, score: float) -> None:
    engine = _engine(db_path)
    try:
        with Session(engine) as session:
            existing = session.execute(
                select(Gap).where(Gap.need == need, Gap.part == part)
            ).scalar_one_or_none()

            if existing is not None:
                existing.score = float(score)
                existing.recorded_at = datetime.utcnow()
            else:
                session.add(
                    Gap(
                        need=need,
                        part=part,
                        score=float(score),
                        recorded_at=datetime.utcnow(),
                    )
                )
            session.commit()
    finally:
        engine.dispose()


def prioritize_gaps(db_path: str, threshold: float = 0.7) -> List[Dict[str, Any]]:
    engine = _engine(db_path)
    try:
        with Session(engine) as session:
            rows = session.execute(
                select(Gap)
                .where(Gap.score >= threshold)
                .order_by(Gap.score.desc(), Gap.need.asc(), Gap.part.asc())
            ).scalars().all()

            return [
                {
                    "id": row.id,
                    "need": row.need,
                    "part": row.part,
                    "score": row.score,
                    "recorded_at": (
                        row.recorded_at.isoformat() if row.recorded_at else None
                    ),
                }
                for row in rows
            ]
    finally:
        engine.dispose()


def list_unmet_needs(db_path: str) -> List[str]:
    engine = _engine(db_path)
    try:
        with Session(engine) as session:
            needs = session.execute(select(Gap.need).distinct()).scalars().all()
            return sorted(needs)
    finally:
        engine.dispose()


def clear_gap_history(db_path: str) -> None:
    engine = _engine(db_path)
    try:
        with Session(engine) as session:
            session.execute(delete(Gap))
            session.commit()
    finally:
        engine.dispose()


def _selftest() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "gap_test.db")

        record_gap(db_path, "need_a", "part_x", 0.65)
        record_gap(db_path, "need_b", "part_y", 0.85)
        record_gap(db_path, "need_a", "part_z", 0.75)
        record_gap(db_path, "need_c", "part_w", 0.95)

        needs = list_unmet_needs(db_path)
        assert sorted(needs) == ["need_a", "need_b", "need_c"], needs

        gaps = prioritize_gaps(db_path)
        assert len(gaps) == 3, gaps
        assert [g["score"] for g in gaps] == [0.95, 0.85, 0.75]
        for g in gaps:
            assert set(g.keys()) >= {"need", "part", "score", "recorded_at"}

        gaps_high = prioritize_gaps(db_path, threshold=0.8)
        assert len(gaps_high) == 2, gaps_high
        assert [g["score"] for g in gaps_high] == [0.95, 0.85]

        clear_gap_history(db_path)
        assert list_unmet_needs(db_path) == []
        assert prioritize_gaps(db_path) == []


if __name__ == "__main__":
    _selftest()
