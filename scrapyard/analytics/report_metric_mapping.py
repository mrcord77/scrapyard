"""
report_metric_mapping - Associate metric ids with report ids for BI reporting (many-to-many mapping table).

### PART-META-JSON
{
  "name": "report_metric_mapping",
  "layer": "analytics",
  "purpose": "Associate metric ids with report ids for BI reporting (many-to-many mapping table).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "map_metric_to_report(session, report_id, metric_id).",
  "outputs": "ReportMetricMappingModel rows (table 'report_metric_mapping').",
  "files_created": [],
  "security_notes": "Pure mapping data via parameterized ORM writes - no expression evaluation, no PII. Ids are opaque strings; uniqueness of (report_id, metric_id) pairs is the integrity concern for consumers.",
  "ai_usage": "Import what you need from `scrapyard.analytics.report_metric_mapping`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.analytics.report_metric_mapping import map_metric_to_report",
  "import_path": "scrapyard.analytics.report_metric_mapping"
}
### END-PART-META
"""
"""Scrapyard analytics report metric mapping module.

Maps report IDs to metric IDs for BI reporting systems using SQLAlchemy 2.x ORM.
"""
import logging
import os
import tempfile

from sqlalchemy import String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class ReportMetricMappingModel(IntPKModel):
    """ORM model for report-metric associations."""
    
    __tablename__ = "report_metric_mapping"
    
    report_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    metric_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    __table_args__ = (
        UniqueConstraint("report_id", "metric_id", name="uix_report_metric"),
    )


def map_metric_to_report(session: Session, report_id: str, metric_id: str) -> None:
    """Create a mapping between a report and a metric.
    
    Args:
        session: Active SQLAlchemy session for database operations.
        report_id: Unique identifier for the report.
        metric_id: Unique identifier for the metric.
    
    Raises:
        ValueError: If report_id or metric_id are empty.
    """
    if not isinstance(report_id, str) or not isinstance(metric_id, str):
        raise TypeError("report_id and metric_id must be strings")
    if not report_id or not metric_id:
        raise ValueError("report_id and metric_id must be non-empty")
    
    mapping = ReportMetricMappingModel(
        report_id=report_id,
        metric_id=metric_id,
    )
    session.add(mapping)
    session.flush()


def _selftest() -> None:
    """Execute offline self-test using temporary SQLite database.
    
    Verifies:
        - map_metric_to_report() persists valid mappings
        - ReportMetricMappingModel schema correctness
        - Type safety and session operations
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_report_metric.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
        
        try:
            # Create schema
            ReportMetricMappingModel.metadata.create_all(engine)
            
            # Test 1: Create mapping and verify with select()
            with Session(engine) as session:
                map_metric_to_report(session, "report_abc", "metric_xyz")
                # Verify via select() within same transaction (flush makes it visible)
                stmt = select(ReportMetricMappingModel).where(
                    ReportMetricMappingModel.report_id == "report_abc",
                    ReportMetricMappingModel.metric_id == "metric_xyz"
                )
                result = session.execute(stmt).scalar_one_or_none()
                assert result is not None, "Mapping not found after flush"
                assert result.report_id == "report_abc"
                assert result.metric_id == "metric_xyz"
                assert isinstance(result.id, int), "IntPKModel should provide integer ID"
                session.commit()
            
            # Test 2: Verify persistence and model reflection
            with Session(engine) as session:
                stmt = select(ReportMetricMappingModel).where(
                    ReportMetricMappingModel.report_id == "report_abc"
                )
                persisted = session.execute(stmt).scalar_one()
                assert persisted.metric_id == "metric_xyz"
                
                # Verify table schema
                assert ReportMetricMappingModel.__tablename__ == "report_metric_mapping"
                table = ReportMetricMappingModel.__table__
                assert "report_id" in table.columns
                assert "metric_id" in table.columns
                assert isinstance(table.columns["report_id"].type, String)
                
            # Test 3: Verify validation
            with Session(engine) as session:
                try:
                    map_metric_to_report(session, "", "metric_123")
                    assert False, "Should raise ValueError for empty report_id"
                except ValueError:
                    pass
                
                try:
                    map_metric_to_report(session, "report_123", "")
                    assert False, "Should raise ValueError for empty metric_id"
                except ValueError:
                    pass
        
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("report_metric_mapping selftest OK")
