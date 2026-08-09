"""
capacity_report — ** The `scrapyard.projects.capacity_report` module provides tools to generate and export capacity usage reports for resource scheduling systems. It enables structured analysis of resource availability

### PART-META-JSON
{
  "name": "capacity_report",
  "layer": "projects",
  "purpose": "Provides tools to generate and export capacity usage reports for resource scheduling systems. It enables structured analysis of resource availability.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: ResourceUsage(...); CapacityReportGenerator(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.capacity_report`.",
  "example": "from scrapyard.projects.capacity_report import *",
  "import_path": "scrapyard.projects.capacity_report"
}
### END-PART-META
"""
from sqlalchemy import func, select, String, Float, DateTime, Integer, create_engine
from sqlalchemy.orm import Session, Mapped, mapped_column, sessionmaker
from datetime import datetime
from typing import Optional, Dict, Any
import os, json, logging, tempfile

logger = logging.getLogger(__name__)

from scrapyard.database.base_model import IntPKModel

class ResourceUsage(IntPKModel):
    __tablename__ = "capacity_report_resource_usage"
    
    resource_id: Mapped[int] = mapped_column(Integer, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    capacity_used: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10))

class CapacityReportGenerator:
    def __init__(self, session: Session):
        self.session = session

    def generate_report(self, start_date: datetime, end_date: datetime, resource_id: Optional[int] = None) -> Dict[str, Any]:
        query = select(ResourceUsage.resource_id, func.sum(ResourceUsage.capacity_used).label('total_capacity_used'))
        
        if resource_id is not None:
            query = query.where(ResourceUsage.resource_id == resource_id)
        
        query = query.where(
            ResourceUsage.start_time >= start_date,
            ResourceUsage.end_time <= end_date
        ).group_by(ResourceUsage.resource_id)

        report_data = {}
        for row in self.session.execute(query):
            res_id, total_capacity_used = row
            report_data[res_id] = {'total_capacity_used': float(total_capacity_used) if total_capacity_used is not None else 0.0}

        return report_data

    def export_report(self, report_data: Dict[str, Any], format: str = "csv") -> bytes:
        if format == "csv":
            if not report_data:
                return b""
            lines = [f"{k},{v['total_capacity_used']}" for k, v in sorted(report_data.items())]
            data_str = "\n".join(lines)
            return data_str.encode('utf-8')
        elif format == "json":
            return json.dumps(report_data).encode('utf-8')
        else:
            raise ValueError(f"Unsupported export format: {format}")

def _selftest():
    from scrapyard.database.base_model import Base
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_file = os.path.join(temp_dir, 'test.db')
        engine = create_engine(f"sqlite:///{db_file}")
        Base.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        try:
            # Insert some test data
            resource_usages = [
                ResourceUsage(resource_id=1, start_time=datetime(2023, 1, 1), end_time=datetime(2023, 1, 2), capacity_used=50.0, unit='GB'),
                ResourceUsage(resource_id=1, start_time=datetime(2023, 1, 2), end_time=datetime(2023, 1, 3), capacity_used=75.0, unit='GB'),
                ResourceUsage(resource_id=2, start_time=datetime(2023, 1, 1), end_time=datetime(2023, 1, 2), capacity_used=40.0, unit='GB')
            ]

            for usage in resource_usages:
                session.add(usage)

            session.commit()

            # Test report generation
            report_gen = CapacityReportGenerator(session)
            start_date = datetime(2023, 1, 1)
            end_date = datetime(2023, 1, 3)

            report_data = report_gen.generate_report(start_date, end_date)
            assert len(report_data) == 2
            assert report_data[1]['total_capacity_used'] == 125.0

            # Test export to CSV
            csv_bytes = report_gen.export_report(report_data, format="csv")
            expected_csv = "1,125.0\n2,40.0"
            assert csv_bytes.decode('utf-8') == expected_csv

            # Test export to JSON
            json_bytes = report_gen.export_report(report_data, format="json")
            expected_json = '{"1": {"total_capacity_used": 125.0}, "2": {"total_capacity_used": 40.0}}'
            assert json.loads(json_bytes.decode('utf-8')) == json.loads(expected_json)

            # Test filtering by resource_id
            filtered_data = report_gen.generate_report(start_date, end_date, resource_id=1)
            assert len(filtered_data) == 1
            assert filtered_data[1]['total_capacity_used'] == 125.0

            # Test empty report
            empty_data = report_gen.generate_report(datetime(2020, 1, 1), datetime(2020, 1, 2))
            assert len(empty_data) == 0
            empty_csv = report_gen.export_report(empty_data, format="csv")
            assert empty_csv == b""

            logger.info("Self-test passed successfully")
        finally:
            session.close()
            engine.dispose()

if __name__ == "__main__":
    _selftest()
