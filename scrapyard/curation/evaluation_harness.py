"""scrapyard.curation.evaluation_harness

Framework for assessing curation accuracy against predefined job descriptions.

### PART-META-JSON
{
  "name": "evaluation_harness",
  "layer": "curation",
  "purpose": "Score curator output against golden job descriptions: compare_results(actual, expected) yields precision/recall-style ComparisonReports; evaluate_job grades one composed metadata.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Expected vs actual Part lists; job_id + metadata dict.",
  "outputs": "ComparisonReport / EvaluationResult dataclasses with match metrics.",
  "files_created": [],
  "security_notes": "Pure in-memory comparison of catalog metadata; no network, no code execution, no PII.",
  "ai_usage": "Use to gate curator changes: run evaluate_job over a golden set before trusting new ranking logic.",
  "example": "from scrapyard.curation.evaluation_harness import compare_results",
  "import_path": "scrapyard.curation.evaluation_harness"
}
### END-PART-META
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from sqlalchemy import Float, String, create_engine, func, select
from sqlalchemy import DateTime, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

_ENV_DB_URL = "SCRAPYARD_EVALUATION_DB_URL"


@dataclass(frozen=True)
class Part:
    """Minimal part identity used for comparison."""

    part_id: str
    version: str = "latest"


@dataclass
class ComparisonReport:
    """Result of comparing an actual part list to an expected part list."""

    matched: List[Part] = field(default_factory=list)
    missing: List[Part] = field(default_factory=list)
    extra: List[Part] = field(default_factory=list)
    mismatched: List[Tuple[Part, Part]] = field(default_factory=list)


@dataclass
class EvaluationResult:
    """Outcome returned by :func:`evaluate_job`."""

    job_id: str
    status: str
    score: float
    timestamp: datetime


class Evaluation(IntPKModel):
    """Stores job evaluation metadata."""

    __tablename__ = "evaluations"

    job_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_evaluations_job_id_timestamp", "job_id", "timestamp"),
    )


class ExpectedPart(IntPKModel):
    """Maps a job_id to its expected parts."""

    __tablename__ = "expected_parts"

    job_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    part_id: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="latest")

    __table_args__ = (
        UniqueConstraint("job_id", "part_id", name="uix_expected_job_part"),
    )


def _default_db_url() -> str:
    """Return the configured evaluation database URL.

    Defaults to an in-memory SQLite database if no environment variable is set.
    """
    return os.environ.get(_ENV_DB_URL, "sqlite:///:memory:")


def _engine(db_url: Optional[str] = None):
    """Create a SQLAlchemy engine for the evaluation database."""
    url = db_url or _default_db_url()
    return create_engine(url, echo=False, future=True)


def _init_schema(engine):
    """Create evaluation tables if they do not exist."""
    IntPKModel.metadata.create_all(engine)


def _part_from_value(value: Any) -> Part:
    """Convert a dict or Part instance into a Part."""
    if isinstance(value, Part):
        return value
    if isinstance(value, dict):
        part_id = value.get("part_id") or value.get("name") or value.get("id")
        if not part_id:
            raise ValueError(f"Part dict missing identifier: {value!r}")
        version = value.get("version", "latest")
        return Part(part_id=str(part_id), version=str(version))
    raise TypeError(f"Unsupported part value: {value!r}")


def _parts_from_metadata(metadata: dict) -> List[Part]:
    """Extract actual parts from a metadata dictionary.

    Supports metadata produced by ``build_metadata_composer`` via the
    ``"parts"`` key, or a metadata that is already a list of parts.
    """
    if not isinstance(metadata, dict):
        raise TypeError("metadata must be a dict")
    raw_parts = metadata.get("parts", [])
    return [_part_from_value(p) for p in raw_parts]


def _load_expected_parts(job_id: str, engine) -> List[Part]:
    """Load expected parts for *job_id* from the database."""
    with Session(engine) as session:
        rows = session.execute(
            select(ExpectedPart).where(ExpectedPart.job_id == job_id)
        ).scalars().all()
        return [Part(r.part_id, r.version) for r in rows]


def _add_expected_parts(
    job_id: str,
    parts: List[Any],
    db_url: Optional[str] = None,
) -> int:
    """Helper to populate ``expected_parts`` for a job.

    Not part of the public API; used by tests and setup scripts.
    """
    engine = _engine(db_url)
    try:
        _init_schema(engine)
        with Session(engine) as session:
            for value in parts:
                part = _part_from_value(value)
                session.add(
                    ExpectedPart(
                        job_id=job_id,
                        part_id=part.part_id,
                        version=part.version,
                    )
                )
            session.commit()
        return len(parts)
    finally:
        engine.dispose()


def compare_results(actual: List[Part], expected: List[Part]) -> ComparisonReport:
    """Compare *actual* parts against *expected* parts.

    Returns a :class:`ComparisonReport` listing matched, missing, extra, and
    version-mismatched parts.
    """
    logger.debug(
        "compare_results: actual=%d, expected=%d", len(actual), len(expected)
    )
    report = ComparisonReport()
    actual_by_id = {p.part_id: p for p in actual}
    expected_by_id = {p.part_id: p for p in expected}

    for exp in expected:
        act = actual_by_id.get(exp.part_id)
        if act is None:
            report.missing.append(exp)
        elif act.version == exp.version:
            report.matched.append(exp)
        else:
            report.mismatched.append((act, exp))

    for act in actual:
        if act.part_id not in expected_by_id:
            report.extra.append(act)

    return report


def evaluate_job(job_id: str, metadata: dict) -> EvaluationResult:
    """Evaluate a curator job against its expected outcome.

    Expected parts are read from the ``expected_parts`` table; actual parts are
    extracted from *metadata*.  The evaluation metadata is stored in the
    ``evaluations`` table and returned as an :class:`EvaluationResult`.
    """
    logger.info("Evaluating job %s", job_id)
    engine = _engine()
    try:
        _init_schema(engine)

        expected = _load_expected_parts(job_id, engine)
        actual = _parts_from_metadata(metadata)
        report = compare_results(actual, expected)

        total_expected = len(expected)
        if total_expected > 0:
            score = len(report.matched) / total_expected
        else:
            score = 1.0 if not report.extra else 0.0

        status = "PASS" if not (report.missing or report.extra or report.mismatched) else "FAIL"
        timestamp = datetime.now(timezone.utc)

        with Session(engine) as session:
            session.add(
                Evaluation(
                    job_id=job_id,
                    timestamp=timestamp,
                    status=status,
                    score=score,
                )
            )
            session.commit()

        logger.info(
            "Job %s evaluated: status=%s score=%.4f matched=%d missing=%d extra=%d mismatched=%d",
            job_id,
            status,
            score,
            len(report.matched),
            len(report.missing),
            len(report.extra),
            len(report.mismatched),
        )
        return EvaluationResult(
            job_id=job_id,
            status=status,
            score=score,
            timestamp=timestamp,
        )
    finally:
        engine.dispose()


def _selftest() -> None:
    """Offline self-test using a temporary SQLite database."""
    import tempfile

    original_url = os.environ.get(_ENV_DB_URL)
    engine = None
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "evaluation_harness_selftest.db")
        db_url = f"sqlite:///{db_path}"
        os.environ[_ENV_DB_URL] = db_url
        try:
            engine = _engine()
            _init_schema(engine)

            # Populate expected parts for a synthetic job.
            _add_expected_parts(
                "job-001",
                [
                    {"part_id": "widget", "version": "1.0"},
                    {"part_id": "gadget", "version": "2.0"},
                    {"part_id": "doohickey", "version": "1.5"},
                ],
            )

            # Perfect metadata should PASS.
            perfect_metadata = {
                "parts": [
                    {"part_id": "widget", "version": "1.0"},
                    {"part_id": "gadget", "version": "2.0"},
                    {"part_id": "doohickey", "version": "1.5"},
                ]
            }
            result = evaluate_job("job-001", perfect_metadata)
            assert result.job_id == "job-001"
            assert result.status == "PASS"
            assert abs(result.score - 1.0) < 1e-9

            # Verify the evaluation row was persisted.
            with Session(engine) as session:
                rows = session.execute(
                    select(Evaluation).where(Evaluation.job_id == "job-001")
                ).scalars().all()
                assert len(rows) == 1
                assert rows[0].status == "PASS"
                assert abs(rows[0].score - 1.0) < 1e-9

            # compare_results should identify mismatches.
            actual = [
                Part("widget", "1.0"),
                Part("gadget", "2.1"),  # version mismatch
                Part("extra", "0.1"),   # unexpected
            ]
            expected = [
                Part("widget", "1.0"),
                Part("gadget", "2.0"),
                Part("missing", "1.0"),  # absent from actual
            ]
            report = compare_results(actual, expected)
            assert len(report.matched) == 1
            assert any(p.part_id == "missing" for p in report.missing)
            assert any(p.part_id == "extra" for p in report.extra)
            assert any(pair[0].part_id == "gadget" for pair in report.mismatched)

            # A second evaluation of the same job with the bad metadata.
            bad_metadata = {
                "parts": [
                    {"part_id": "widget", "version": "1.0"},
                    {"part_id": "gadget", "version": "2.1"},
                    {"part_id": "extra", "version": "0.1"},
                ]
            }
            result2 = evaluate_job("job-001", bad_metadata)
            assert result2.status == "FAIL"
            assert result2.score < 1.0

            with Session(engine) as session:
                count = session.execute(
                    select(func.count()).select_from(Evaluation).where(Evaluation.job_id == "job-001")
                ).scalar()
                assert count == 2

            logger.info("scrapyard.curation.evaluation_harness._selftest passed")
        finally:
            if engine is not None:
                engine.dispose()
            if original_url is None:
                os.environ.pop(_ENV_DB_URL, None)
            else:
                os.environ[_ENV_DB_URL] = original_url


if __name__ == "__main__":
    _selftest()
