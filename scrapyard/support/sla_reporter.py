"""scrapyard.support.sla_reporter

Generate performance reports and SLA compliance summaries.

### PART-META-JSON
{
  "name": "sla_reporter",
  "layer": "support",
  "purpose": "SLA report scaffolding: generate_report(start, end, service_id) builds an SLAReport with five linked ReportMetric rows (availability, uptime/downtime seconds, mean response time, error rate), computes compliance against a configurable threshold, and optionally persists via a caller session. HONEST LIMIT: metric VALUES are synthetic - deterministically derived from a hash of (service_id, window), not measured from any telemetry. This part provides the report schema, persistence, and compliance math; wire _make_metrics to real monitoring data before trusting the numbers.",
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "generate_report(start_dt, end_dt, service_id, session=None, sla_threshold=99.9); end < start raises ValueError.",
  "outputs": "SLAReport + ReportMetric ORM rows (sla_reports / report_metrics tables) with compliance_status 'compliant'|'breached'.",
  "files_created": [],
  "security_notes": "The headline risk is misrepresentation, not exploitation: as shipped the availability/response/error figures are hash-seeded placeholders, so a report presented to a customer as real SLA evidence would be fabricated data - replace _make_metrics with a real telemetry source first (the deterministic seed makes reports reproducible for tests). No network, subprocess, or secret handling; persistence only happens when the caller passes a session.",
  "ai_usage": "report = generate_report(window_start, window_end, 'svc-api', session=session); check report.compliance_status; replace _make_metrics for production.",
  "example": "from scrapyard.support.sla_reporter import generate_report",
  "import_path": "scrapyard.support.sla_reporter"
}
### END-PART-META
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List

import hashlib
import logging
import os
import tempfile
import time

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

__part_meta__ = {
    "name": "sla_reporter",
    "layer": "support",
    "status": "core",
    "import_path": "scrapyard.support.sla_reporter",
}


class SLAReport(IntPKModel):
    __tablename__ = "sla_reports"

    service_id: Mapped[str] = mapped_column(String(255), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    sla_threshold: Mapped[float] = mapped_column(Float, default=99.9)
    availability_pct: Mapped[float] = mapped_column(Float, default=0.0)
    compliance_status: Mapped[str] = mapped_column(String(50), default="unknown")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    metrics: Mapped[List[ReportMetric]] = relationship(
        "ReportMetric",
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="select",
    )


class ReportMetric(IntPKModel):
    __tablename__ = "report_metrics"

    report_id: Mapped[int] = mapped_column(
        ForeignKey("sla_reports.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=True)
    threshold: Mapped[float] = mapped_column(Float, nullable=True)
    compliant: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    report: Mapped[SLAReport] = relationship("SLAReport", back_populates="metrics")


def _hash_seed(service_id: str, start: datetime, end: datetime) -> int:
    payload = f"{service_id}|{start.isoformat()}|{end.isoformat()}"
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest(), 16)


def _make_metrics(report: SLAReport) -> List[ReportMetric]:
    total_seconds = max((report.end_time - report.start_time).total_seconds(), 0.0)
    seed = _hash_seed(report.service_id, report.start_time, report.end_time)

    availability = 99.0 + (seed % 1000) / 1000.0
    availability = round(availability, 4)
    uptime_seconds = total_seconds * availability / 100.0
    downtime_seconds = total_seconds - uptime_seconds

    response_time = float(50 + (seed % 450))
    error_rate = round(100.0 - availability, 4)

    return [
        ReportMetric(
            name="availability_pct",
            value=availability,
            unit="%",
            threshold=report.sla_threshold,
            compliant=availability >= report.sla_threshold,
        ),
        ReportMetric(
            name="uptime_seconds",
            value=uptime_seconds,
            unit="s",
        ),
        ReportMetric(
            name="downtime_seconds",
            value=downtime_seconds,
            unit="s",
        ),
        ReportMetric(
            name="mean_response_time_ms",
            value=response_time,
            unit="ms",
            threshold=500.0,
            compliant=response_time <= 500.0,
        ),
        ReportMetric(
            name="error_rate_pct",
            value=error_rate,
            unit="%",
            threshold=round(100.0 - report.sla_threshold, 4),
            compliant=error_rate <= round(100.0 - report.sla_threshold, 4),
        ),
    ]


def generate_report(
    start: datetime,
    end: datetime,
    service_id: str,
    session: Optional[Session] = None,
    sla_threshold: float = 99.9,
) -> SLAReport:
    """Generate an SLAReport with calculated metrics for the requested window."""
    if end < start:
        raise ValueError("end must be greater than or equal to start")

    report = SLAReport(
        service_id=service_id,
        start_time=start,
        end_time=end,
        sla_threshold=sla_threshold,
    )
    report.metrics = _make_metrics(report)

    avail = next(m for m in report.metrics if m.name == "availability_pct")
    report.availability_pct = avail.value
    report.compliance_status = "compliant" if avail.compliant else "breached"

    if session is not None:
        session.add(report)
        session.commit()
        session.refresh(report)

    return report


def _selftest() -> None:
    deadline = time.time() + 20.0

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "sla_reporter_selftest.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        try:
            IntPKModel.metadata.create_all(engine)

            with Session(engine) as session:
                start = datetime(2024, 1, 1, tzinfo=timezone.utc)
                end = datetime(2024, 1, 2, tzinfo=timezone.utc)
                report = generate_report(start, end, "svc-selftest", session=session)

                assert isinstance(report, SLAReport)
                assert report.id is not None
                assert report.service_id == "svc-selftest"
                assert report.availability_pct >= 0.0
                assert report.compliance_status in ("compliant", "breached")

                metrics = report.metrics
                assert len(metrics) == 5
                by_name = {m.name: m for m in metrics}
                assert "availability_pct" in by_name
                assert "downtime_seconds" in by_name

                avail = by_name["availability_pct"]
                assert avail.compliant == (avail.value >= report.sla_threshold)

                loaded_report = session.execute(
                    select(SLAReport).where(SLAReport.id == report.id)
                ).scalar_one()
                assert loaded_report.availability_pct == report.availability_pct
                assert len(loaded_report.metrics) == 5

                stored_metrics = (
                    session.execute(
                        select(ReportMetric).where(ReportMetric.report_id == report.id)
                    )
                    .scalars()
                    .all()
                )
                assert len(stored_metrics) == 5
                for m in stored_metrics:
                    assert m.report_id == report.id
                    assert m.name in by_name
                    assert by_name[m.name].value == m.value
        finally:
            engine.dispose()

    assert time.time() < deadline, "self-test exceeded 20 seconds"


if __name__ == "__main__":
    _selftest()
