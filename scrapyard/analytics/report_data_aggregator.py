"""
report_data_aggregator - Aggregate metric data over time windows for report generation.

### PART-META-JSON
{
  "name": "report_data_aggregator",
  "layer": "analytics",
  "purpose": "Aggregate metric data over time windows for report generation.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "aggregate_data(metric_id, window_id, start, end); DataAggregator over MetricData rows.",
  "outputs": "Aggregation dicts (sum/avg/count) computed from MetricData (table 'report_data_aggregator_metric_data' or as declared).",
  "files_created": [],
  "security_notes": "Read-only aggregation with parameterized queries; metric ids are opaque strings, never interpolated into SQL. No PII stored beyond metric values.",
  "ai_usage": "Import what you need from `scrapyard.analytics.report_data_aggregator`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.analytics.report_data_aggregator import aggregate_data",
  "import_path": "scrapyard.analytics.report_data_aggregator"
}
### END-PART-META
"""
from sqlalchemy import String, Float, DateTime, func, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import logging
import tempfile
import os

logger = logging.getLogger(__name__)


class MetricData(IntPKModel):
    __tablename__ = "metric_data"
    metric_id: Mapped[str] = mapped_column(String(255))
    window_id: Mapped[str] = mapped_column(String(255))
    value: Mapped[Optional[float]] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DataAggregator:
    def __init__(self, session: Session):
        self.session = session
        logger.debug("DataAggregator initialized with session")

    def compute(self, metric_id: str, window_id: str, start: datetime, end: datetime) -> Dict[str, Any]:
        logger.info(f"Computing aggregate for metric_id={metric_id}, window_id={window_id}")
        query = (
            select(
                func.sum(MetricData.value).label("sum_value"),
                func.min(MetricData.timestamp).label("min_timestamp"),
                func.max(MetricData.timestamp).label("max_timestamp"),
            )
            .where(
                MetricData.metric_id == metric_id,
                MetricData.window_id == window_id,
                MetricData.timestamp >= start,
                MetricData.timestamp <= end,
            )
        )
        result = self.session.execute(query).one_or_none()
        
        # Handle timezone awareness for SQLite aggregate compatibility
        min_ts = result.min_timestamp if result else None
        max_ts = result.max_timestamp if result else None
        
        # SQLite may return naive datetimes from aggregate functions; ensure UTC timezone
        if min_ts is not None and min_ts.tzinfo is None:
            min_ts = min_ts.replace(tzinfo=timezone.utc)
        if max_ts is not None and max_ts.tzinfo is None:
            max_ts = max_ts.replace(tzinfo=timezone.utc)
            
        return {
            "sum_value": float(result.sum_value) if result and result.sum_value is not None else 0.0,
            "min_timestamp": min_ts,
            "max_timestamp": max_ts,
        }


def aggregate_data(metric_id: str, window_id: str, start: datetime, end: datetime) -> Dict[str, Any]:
    logger.info(f"Aggregating data for metric_id={metric_id}")
    session = Session()
    try:
        aggregator = DataAggregator(session)
        return aggregator.compute(metric_id, window_id, start, end)
    finally:
        session.close()


def _selftest():
    global Session
    logger.info("Starting _selftest")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        # Save original Session class to restore later
        _OriginalSession = Session
        
        # Override module Session with bound sessionmaker for testing
        Session = sessionmaker(bind=engine)
        
        # Create tables
        MetricData.metadata.create_all(engine)
        
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=6)
        end = now
        metric_id = "metric1"
        window_id = "window1"
        
        # Insert test data
        setup_session = Session()
        try:
            setup_session.add(MetricData(metric_id=metric_id, window_id=window_id, value=10.5, timestamp=start))
            setup_session.add(MetricData(metric_id=metric_id, window_id=window_id, value=20.5, timestamp=end))
            setup_session.commit()
        finally:
            setup_session.close()
        
        # Test DataAggregator
        agg_session = Session()
        try:
            aggregator = DataAggregator(agg_session)
            result = aggregator.compute(metric_id, window_id, start, end)
            assert result["sum_value"] == 31.0, f"Expected sum 31.0, got {result['sum_value']}"
            assert result["min_timestamp"] == start, f"Expected min_timestamp {start}, got {result['min_timestamp']}"
            assert result["max_timestamp"] == end, f"Expected max_timestamp {end}, got {result['max_timestamp']}"
            logger.info("DataAggregator compute test passed")
        finally:
            agg_session.close()
        
        # Test aggregate_data function (uses module-level Session)
        result = aggregate_data(metric_id, window_id, start, end)
        assert result["sum_value"] == 31.0, f"Expected sum 31.0, got {result['sum_value']}"
        assert result["min_timestamp"] == start, f"Expected min_timestamp {start}, got {result['min_timestamp']}"
        assert result["max_timestamp"] == end, f"Expected max_timestamp {end}, got {result['max_timestamp']}"
        logger.info("aggregate_data test passed")
        
        # Restore original Session
        Session = _OriginalSession
        
    logger.info("_selftest completed successfully")


if __name__ == "__main__":
    _selftest()
