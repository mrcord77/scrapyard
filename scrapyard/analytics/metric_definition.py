"""
metric_definition — Metric and aggregation-window definitions for BI reporting.

### PART-META-JSON
{
  "name": "metric_definition",
  "layer": "analytics",
  "purpose": "Define metrics (expression + data source) and aggregation windows; delegate report templates and scheduled runs to their canonical sibling parts.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "create_metric_definition(name, expression, data_source); create_aggregation_window(name, start_offset, end_offset) with offsets like '-7d'/'+1h'/'30m'; schedule_report(report_id, interval, next_run); create_report_template(name, format_type, content).",
  "outputs": "MetricDefinitionModel and AggregationWindowModel (owned here); ScheduledReportRun and ReportTemplateModel are IMPORTED from scrapyard.analytics.scheduled_report_run / scrapyard.analytics.report_template (one canonical model set, co-importable).",
  "files_created": [],
  "security_notes": "Metric expressions (e.g. 'SUM(amount)') are stored as opaque strings and NEVER executed or interpolated into SQL by this part; any executor consuming them must parameterize or whitelist them - do not string-format them into queries. Offsets and intervals are regex-validated before storage.",
  "ai_usage": "Import from `scrapyard.analytics.metric_definition`; templates/scheduled runs come from the canonical sibling parts and share IntPKModel.metadata.",
  "example": "from scrapyard.analytics.metric_definition import create_metric_definition",
  "import_path": "scrapyard.analytics.metric_definition"
}
### END-PART-META
"""

"""
Define metrics, aggregation windows, and report scheduling for BI reporting.

FEATURES:
- Centralized metric definition with expression and data source tracking
- Time-based aggregation window configuration
- Scheduling of report execution with flexible intervals
- Report template structure and format definitions
- ORM models for persistent storage
- Type-safe API with full type hints
- Self-contained unit testing with temporary SQLite
- No runtime dependencies at import time

PUBLIC API:
def create_metric_definition(name: str, expression: str, data_source: str) -> MetricDefinitionModel
class MetricDefinitionModel(IntPKModel):
    name: str
    expression: str
    data_source: str

def create_aggregation_window(name: str, start_offset: str, end_offset: str) -> AggregationWindowModel
class AggregationWindowModel(IntPKModel):
    name: str
    start_offset: str
    end_offset: str

def schedule_report(report_id: str, interval: str, next_run: datetime) -> ScheduledReportRun
    # ScheduledReportRun is the canonical model from scrapyard.analytics.scheduled_report_run

def create_report_template(name: str, format_type: str, content: str) -> ReportTemplateModel
    # ReportTemplateModel is the canonical model from scrapyard.analytics.report_template

TABLES (owned by this part):
- metric_definition
- aggregation_window
(report templates and scheduled runs live in their canonical parts' tables)

SELFTEST MUST PROVE:
- Create, retrieve, and delete metric definitions
- Validate aggregation window start/end offset parsing
- Schedule and query report runs
- Create and query report templates
- ORM persistence and retrieval with SQLite
- Type hints and function signatures are enforced
- No runtime errors during import
- All models are correctly mapped with __tablename__
"""

from sqlalchemy import String, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
import re
import logging
import tempfile
import os

# Canonical models owned by dedicated sibling parts (do NOT redefine here).
from scrapyard.analytics.report_template import ReportTemplateModel, create_report_template as _create_canonical_template
from scrapyard.analytics.scheduled_report_run import ScheduledReportRun, _parse_interval

logger = logging.getLogger(__name__)

STATUS = "core"


def _validate_offset(offset: str) -> None:
    """Validate aggregation offset format (e.g., -7d, +1h, 30m)."""
    if not isinstance(offset, str) or not offset:
        raise ValueError("Offset must be a non-empty string")
    if not re.match(r'^[+-]?\d+[dhm]$', offset):
        raise ValueError(f"Invalid offset format: {offset}. Expected format like '-7d', '+1h', or '30m'.")


class MetricDefinitionModel(IntPKModel):
    __tablename__ = "metric_definition"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    expression: Mapped[str] = mapped_column(String(500), nullable=False)
    data_source: Mapped[str] = mapped_column(String(255), nullable=False)


class AggregationWindowModel(IntPKModel):
    __tablename__ = "aggregation_window"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_offset: Mapped[str] = mapped_column(String(50), nullable=False)
    end_offset: Mapped[str] = mapped_column(String(50), nullable=False)


def create_metric_definition(name: str, expression: str, data_source: str) -> MetricDefinitionModel:
    """Create a new metric definition."""
    return MetricDefinitionModel(
        name=name,
        expression=expression,
        data_source=data_source
    )


def create_aggregation_window(name: str, start_offset: str, end_offset: str) -> AggregationWindowModel:
    """Create a new aggregation window with validated offsets."""
    _validate_offset(start_offset)
    _validate_offset(end_offset)
    return AggregationWindowModel(
        name=name,
        start_offset=start_offset,
        end_offset=end_offset
    )


def schedule_report(report_id: str, interval: str, next_run: datetime) -> ScheduledReportRun:
    """Schedule a report run using the canonical ScheduledReportRun model."""
    if not isinstance(next_run, datetime):
        raise TypeError("next_run must be a datetime instance")
    _parse_interval(interval)  # raises ValueError on invalid interval
    return ScheduledReportRun(
        report_id=report_id,
        interval=interval,
        next_run=next_run
    )


def create_report_template(name: str, format_type: str, content: str) -> ReportTemplateModel:
    """Create a report template using the canonical ReportTemplateModel.

    `format_type` maps to the canonical model's `format` column (PDF/CSV/HTML).
    """
    return _create_canonical_template(name=name, format=format_type, content=content)


def _selftest() -> None:
    """Run self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            # Create tables
            IntPKModel.metadata.create_all(engine)
            
            with Session(engine) as session:
                # Test MetricDefinitionModel: Create, retrieve, delete
                metric = create_metric_definition(
                    name="Total Revenue",
                    expression="SUM(amount)",
                    data_source="sales_db"
                )
                session.add(metric)
                session.commit()
                
                # Verify tablename
                assert MetricDefinitionModel.__tablename__ == "metric_definition"
                
                # Retrieve
                retrieved = session.get(MetricDefinitionModel, metric.id)
                assert retrieved is not None
                assert retrieved.name == "Total Revenue"
                assert retrieved.expression == "SUM(amount)"
                assert retrieved.data_source == "sales_db"
                
                # Delete
                session.delete(retrieved)
                session.commit()
                assert session.get(MetricDefinitionModel, metric.id) is None
                
                # Test AggregationWindowModel: Validation and persistence
                assert AggregationWindowModel.__tablename__ == "aggregation_window"
                
                # Test invalid offset raises ValueError
                try:
                    create_aggregation_window("Invalid", "not_an_offset", "0d")
                    assert False, "Should have raised ValueError for invalid offset"
                except ValueError:
                    pass
                
                # Test valid window
                window = create_aggregation_window(
                    name="Rolling7Day",
                    start_offset="-7d",
                    end_offset="0h"
                )
                session.add(window)
                session.commit()
                
                retrieved_window = session.get(AggregationWindowModel, window.id)
                assert retrieved_window.name == "Rolling7Day"
                assert retrieved_window.start_offset == "-7d"
                assert retrieved_window.end_offset == "0h"
                
                # Test schedule_report -> canonical ScheduledReportRun
                assert ScheduledReportRun.__tablename__ == "scheduled_report_run_scheduled_report_run"

                run_time = datetime(2024, 6, 15, 10, 30, 0)
                scheduler = schedule_report(
                    report_id="monthly-sales-001",
                    interval="1d",
                    next_run=run_time
                )
                session.add(scheduler)
                session.commit()

                retrieved_sched = session.get(ScheduledReportRun, scheduler.id)
                assert retrieved_sched.report_id == "monthly-sales-001"
                assert retrieved_sched.interval == "1d"
                assert retrieved_sched.next_run.replace(tzinfo=None) == run_time

                # Invalid interval is rejected before hitting the DB
                try:
                    schedule_report("bad", "not_an_interval", run_time)
                    assert False, "invalid interval should raise ValueError"
                except ValueError:
                    pass

                # Test create_report_template -> canonical ReportTemplateModel
                assert ReportTemplateModel.__tablename__ == "report_template_report_template"

                template = create_report_template(
                    name="Executive Summary",
                    format_type="HTML",
                    content='<h1>Summary</h1>'
                )
                session.add(template)
                session.commit()

                retrieved_template = session.get(ReportTemplateModel, template.id)
                assert retrieved_template.name == "Executive Summary"
                assert retrieved_template.format == "HTML"
                assert retrieved_template.content == '<h1>Summary</h1>'

                # Invalid format is rejected by the canonical validator
                try:
                    create_report_template("Bad", "json", "{}")
                    assert False, "invalid format should raise ValueError"
                except ValueError:
                    pass
                
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("metric_definition selftest OK")
