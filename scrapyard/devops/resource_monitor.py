"""
resource_monitor — Monitor resource usage and health of deployed services. Provides structured tracking and querying of CPU, memory, and service health metrics for operational visibility and alerting.

### PART-META-JSON
{
  "name": "resource_monitor",
  "layer": "devops",
  "purpose": "Monitor resource usage and health of deployed services. Provides structured tracking and querying of CPU, memory, and service health metrics for operational visibility and alerting.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "log_shipper"
  ],
  "inputs": "Public API: monitor_resources(service_id, metrics, _session); ResourceUsage(...).",
  "outputs": "Returns: monitor_resources -> None.",
  "files_created": [
    "resource_usage"
  ],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.devops.resource_monitor`.",
  "example": "from scrapyard.devops.resource_monitor import *",
  "import_path": "scrapyard.devops.resource_monitor"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, Float, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from typing import Dict, Any, Optional
import os, logging, tempfile

# Configure logger
logger = logging.getLogger(__name__)

class ResourceUsage(IntPKModel):
    __tablename__ = "resource_monitor_resource_usage"
    service_id: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    cpu_percent: Mapped[float] = mapped_column(Float)
    memory_percent: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))

def monitor_resources(service_id: str, metrics: Dict[str, Any], _session: Optional[Session] = None) -> None:
    """Monitor and log resource usage for a given service."""
    close_session = False
    if _session is None:
        _session = Session()
        close_session = True
    
    try:
        new_usage = ResourceUsage(
            service_id=service_id,
            cpu_percent=float(metrics.get('cpu_percent', 0.0)),
            memory_percent=float(metrics.get('memory_percent', 0.0)),
            status=str(metrics.get('status', 'unknown'))
        )
        _session.add(new_usage)
        _session.commit()
    except Exception as e:
        logger.error(f"Failed to log resource usage: {e}")
        _session.rollback()
        raise
    finally:
        if close_session:
            _session.close()

def _selftest():
    """Self-test the module."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'resource_monitor.db')
        engine = create_engine(f"sqlite:///{db_path}")
        IntPKModel.metadata.create_all(engine)

        service_id = "test_service"
        metrics = {
            'cpu_percent': 50.2,
            'memory_percent': 75.1,
            'status': 'healthy'
        }
        
        try:
            with Session(engine) as session:
                monitor_resources(service_id, metrics, _session=session)
                result = session.query(ResourceUsage).filter_by(service_id=service_id).first()
                assert result is not None
                assert result.cpu_percent == metrics['cpu_percent']
                assert result.memory_percent == metrics['memory_percent']
                assert result.status == metrics['status']
                logger.info("ResourceUsage model creates table structure and monitor_resources() inserts valid records.")
        except Exception as e:
            logger.error(f"Self-test failed: {e}")
            raise


if __name__ == "__main__":
    _selftest()
