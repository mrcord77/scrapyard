"""scrapyard.support.agent_performance

Tracks agent performance metrics in support desk systems, enabling data-driven
evaluations and reporting.  Provides reusable, scalable logic for calculating
scores and generating structured reports from ticket data.

### PART-META-JSON
{
  "name": "agent_performance",
  "layer": "support",
  "purpose": "Support-desk agent performance tracking: AgentMetric rows hold tickets_handled and total_resolution_time per agent; calculate_agent_score() derives a score clamped to [0,1] from the fixed heuristic (tickets/100 - total_resolution_hours), and generate_agent_report() persists a PerformanceReport row and returns a frozen AgentReport dataclass with average resolution time. The scoring formula is a simple built-in heuristic, not a configurable or validated model - tune it before using scores for real evaluations.",
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "_configure_engine(engine) once; AgentMetric rows seeded by the composing app; calculate_agent_score(agent_id); generate_agent_report(agent_id).",
  "outputs": "Float scores in [0,1]; AgentReport dataclasses; persisted PerformanceReport rows. Unknown agent ids raise ValueError.",
  "files_created": [],
  "security_notes": "Agent performance scores are employment-sensitive data: restrict who can read reports and who can write AgentMetric rows (a metric writer can manufacture any score). The hard-coded formula saturates at 100 tickets and penalizes long total resolution time linearly - decisions made on it without calibration are a fairness risk, which is why the metadata flags it. No authentication, network, or secret handling in this module.",
  "ai_usage": "_configure_engine(engine); seed AgentMetric rows from your ticket system; report = generate_agent_report(agent_id).",
  "example": "from scrapyard.support.agent_performance import generate_agent_report",
  "import_path": "scrapyard.support.agent_performance"
}
### END-PART-META
"""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Callable
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

_engine = None
_SessionFactory: Callable[..., Session] = sessionmaker(
    class_=Session, expire_on_commit=False
)


@dataclass(frozen=True)
class AgentReport:
    agent_id: int
    report_timestamp: datetime
    ticket_count: int
    average_resolution_time: float
    score: float


class AgentMetric(IntPKModel):
    __tablename__ = "agent_metric"

    agent_id: Mapped[int] = mapped_column(unique=True, index=True)
    tickets_handled: Mapped[int] = mapped_column(default=0)
    total_resolution_time: Mapped[float] = mapped_column(default=0.0)


class PerformanceReport(IntPKModel):
    __tablename__ = "performance_report"

    agent_id: Mapped[int] = mapped_column(index=True)
    report_timestamp: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    ticket_count: Mapped[int] = mapped_column()
    average_resolution_time: Mapped[float] = mapped_column()
    score: Mapped[float] = mapped_column()


def _configure_engine(engine) -> None:
    """Bind the module's global session factory to the supplied engine."""
    global _engine
    _engine = engine


def _get_session() -> Session:
    if _engine is None:
        raise RuntimeError(
            "No database engine is configured for agent_performance."
        )
    return _SessionFactory(bind=_engine)


def calculate_agent_score(agent_id: int) -> float:
    """Return a normalized performance score for the given agent."""
    with _get_session() as session:
        metric = session.execute(
            select(AgentMetric).where(AgentMetric.agent_id == agent_id).limit(1)
        ).scalar_one_or_none()

        if metric is None:
            raise ValueError(f"No metrics found for agent {agent_id}")

        ticket_count = metric.tickets_handled
        total_resolution_time = metric.total_resolution_time

        # Higher ticket counts and lower total resolution times are better.
        score = (ticket_count / 100.0) - (total_resolution_time / 3600.0)
        return float(max(0.0, min(score, 1.0)))


def generate_agent_report(agent_id: int) -> AgentReport:
    """Generate and persist a performance report for the given agent."""
    with _get_session() as session:
        metric = session.execute(
            select(AgentMetric).where(AgentMetric.agent_id == agent_id).limit(1)
        ).scalar_one_or_none()

        if metric is None:
            raise ValueError(f"No metrics found for agent {agent_id}")

        ticket_count = metric.tickets_handled
        total_resolution_time = metric.total_resolution_time
        average_resolution_time = (
            total_resolution_time / max(ticket_count, 1)
            if ticket_count
            else 0.0
        )

        score = calculate_agent_score(agent_id)

        report = AgentReport(
            agent_id=agent_id,
            report_timestamp=datetime.now(timezone.utc),
            ticket_count=ticket_count,
            average_resolution_time=average_resolution_time,
            score=score,
        )

        db_report = PerformanceReport(
            agent_id=agent_id,
            ticket_count=ticket_count,
            average_resolution_time=average_resolution_time,
            score=score,
        )
        session.add(db_report)
        session.commit()

        logger.info("Generated performance report for agent %s", agent_id)
        return report


def _selftest() -> None:
    """Offline module self-test using a temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")

        _configure_engine(engine)

        try:
            IntPKModel.metadata.create_all(engine)

            with _get_session() as session:
                session.add_all(
                    [
                        AgentMetric(
                            agent_id=1,
                            tickets_handled=50,
                            total_resolution_time=240.0,
                        ),
                        AgentMetric(
                            agent_id=2,
                            tickets_handled=30,
                            total_resolution_time=60.0,
                        ),
                    ]
                )
                session.commit()

            score1 = calculate_agent_score(1)
            score2 = calculate_agent_score(2)
            assert isinstance(score1, float)
            assert isinstance(score2, float)
            assert 0.0 <= score1 <= 1.0
            assert 0.0 <= score2 <= 1.0

            report1 = generate_agent_report(1)
            assert isinstance(report1, AgentReport)
            assert report1.agent_id == 1
            assert report1.ticket_count == 50
            assert 4.8 <= report1.average_resolution_time <= 4.9
            assert 0.43 <= report1.score <= 0.44

            report2 = generate_agent_report(2)
            assert isinstance(report2, AgentReport)
            assert report2.agent_id == 2
            assert report2.ticket_count == 30
            assert 1.9 <= report2.average_resolution_time <= 2.1
            assert 0.28 <= report2.score <= 0.29

            with _get_session() as session:
                stored = session.execute(
                    select(PerformanceReport).where(
                        PerformanceReport.agent_id == 1
                    )
                ).scalars().all()
                assert len(stored) >= 1

        finally:
            engine.dispose()

    logger.info("Selftest completed successfully")


if __name__ == "__main__":
    _selftest()
