"""
governance_dashboard — Store governance events/metrics and produce dashboard chart data.

### PART-META-JSON
{
  "name": "governance_dashboard",
  "layer": "audit_governance",
  "purpose": "Data layer for a governance dashboard: save_governance_event() persists typed events with JSON-safe metadata (datetimes auto-converted to ISO strings), load_governance_data() returns events in a time range, and generate_dashboard_chart() aggregates GovernanceMetric rows for one metric into a Plot dataclass ready for charting. Chart rendering itself is the caller's job - this part produces the data series only.",
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "A caller-supplied SQLAlchemy Session; save_governance_event(session, event_type, metadata_dict); load_governance_data(session, start, end); generate_dashboard_chart(session, metric_name, start, end). Metric rows are inserted by the composing app.",
  "outputs": "GovernanceEvent / GovernanceMetric rows; event dict lists; Plot(metric, start, end, data=[{timestamp, value, ...}]).",
  "files_created": [],
  "security_notes": "Event metadata is stored verbatim as JSON - do not put secrets or raw PII in it; there is no scrubbing or size cap, so bound metadata size upstream to avoid DB bloat. Timestamps default to now(UTC) when the caller omits one, but caller-supplied timestamps are trusted as-is (events can be backdated) - restrict who may write events if your audit posture forbids that. No authentication or tenant isolation: scope queries in the composing app.",
  "ai_usage": "save_governance_event(session, 'policy_violation', {'severity': 'high', 'source': 'x'}); chart = generate_dashboard_chart(session, 'compliance_rate', start, end).",
  "example": "from scrapyard.audit_governance.governance_dashboard import save_governance_event, generate_dashboard_chart",
  "import_path": "scrapyard.audit_governance.governance_dashboard"
}
### END-PART-META
"""
from sqlalchemy import String, DateTime, Float, JSON, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import logging
import tempfile
import os

logger = logging.getLogger(__name__)


class GovernanceEvent(IntPKModel):
    __tablename__ = "governance_events"
    
    event_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class GovernanceMetric(IntPKModel):
    __tablename__ = "governance_metrics"
    
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    dimensions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


@dataclass
class Plot:
    metric: str
    start: datetime
    end: datetime
    data: List[Dict[str, Any]]


def _make_json_safe(obj: Any) -> Any:
    """Recursively convert datetime objects to ISO format strings for JSON serialization."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    return obj


def save_governance_event(session: Session, event_type: str, metadata: Dict) -> None:
    """Log a governance event with structured metadata."""
    # Convert metadata to JSON-serializable format (handles datetime objects)
    safe_metadata = _make_json_safe(metadata)
    
    timestamp = metadata.get("timestamp")
    if not isinstance(timestamp, datetime):
        timestamp = datetime.now(timezone.utc)
    
    source = metadata.get("source", "unknown")
    
    event = GovernanceEvent(
        event_type=event_type,
        event_metadata=safe_metadata,
        timestamp=timestamp,
        source=source
    )
    session.add(event)
    session.commit()


def load_governance_data(session: Session, start: datetime, end: datetime) -> List[Dict]:
    """Load governance events within the specified time range."""
    stmt = select(GovernanceEvent).where(
        GovernanceEvent.timestamp >= start,
        GovernanceEvent.timestamp <= end
    ).order_by(GovernanceEvent.timestamp)
    
    result = session.execute(stmt)
    events = result.scalars().all()
    
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "metadata": e.event_metadata,
            "timestamp": e.timestamp,
            "source": e.source
        }
        for e in events
    ]


def generate_dashboard_chart(session: Session, metric: str, start: datetime, end: datetime) -> Plot:
    """Generate chart data for a specific metric over time."""
    stmt = select(GovernanceMetric).where(
        GovernanceMetric.metric_name == metric,
        GovernanceMetric.period_start >= start,
        GovernanceMetric.period_end <= end
    ).order_by(GovernanceMetric.period_start)
    
    result = session.execute(stmt)
    metrics = result.scalars().all()
    
    chart_data = [
        {
            "timestamp": m.period_start,
            "value": m.value,
            "period_end": m.period_end,
            "dimensions": m.dimensions
        }
        for m in metrics
    ]
    
    return Plot(
        metric=metric,
        start=start,
        end=end,
        data=chart_data
    )


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    from sqlalchemy.orm import sessionmaker
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_governance.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        IntPKModel.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        try:
            now = datetime.now(timezone.utc)
            start = now - timedelta(days=7)
            end = now + timedelta(days=1)
            
            # Test event logging and retrieval
            save_governance_event(
                session, 
                "policy_violation", 
                {"severity": "high", "source": "system_a", "timestamp": now - timedelta(days=1)}
            )
            save_governance_event(
                session,
                "compliance_check",
                {"result": "passed", "source": "system_b", "timestamp": now - timedelta(hours=5)}
            )
            
            events = load_governance_data(session, start, end)
            assert len(events) == 2, f"Expected 2 events, got {len(events)}"
            assert events[0]["event_type"] == "policy_violation"
            assert events[1]["event_type"] == "compliance_check"
            
            # Test metric aggregation and chart generation
            metrics_data = [
                GovernanceMetric(
                    metric_name="compliance_rate",
                    period_start=now - timedelta(days=3),
                    period_end=now - timedelta(days=2),
                    value=95.5,
                    dimensions={"region": "us-east"}
                ),
                GovernanceMetric(
                    metric_name="compliance_rate",
                    period_start=now - timedelta(days=2),
                    period_end=now - timedelta(days=1),
                    value=97.0,
                    dimensions={"region": "us-east"}
                ),
                GovernanceMetric(
                    metric_name="violation_count",
                    period_start=now - timedelta(days=3),
                    period_end=now - timedelta(days=2),
                    value=5.0,
                    dimensions={"severity": "high"}
                )
            ]
            for m in metrics_data:
                session.add(m)
            session.commit()
            
            chart = generate_dashboard_chart(session, "compliance_rate", start, end)
            assert chart.metric == "compliance_rate"
            assert len(chart.data) == 2
            assert chart.data[0]["value"] == 95.5
            assert chart.data[1]["value"] == 97.0
            
            violation_chart = generate_dashboard_chart(session, "violation_count", start, end)
            assert len(violation_chart.data) == 1
            assert violation_chart.data[0]["value"] == 5.0
            
            empty_chart = generate_dashboard_chart(
                session, 
                "compliance_rate", 
                now + timedelta(days=10), 
                now + timedelta(days=20)
            )
            assert len(empty_chart.data) == 0
            
            logger.info("Governance dashboard self-test completed successfully")
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
