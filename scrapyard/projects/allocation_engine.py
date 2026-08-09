"""
allocation_engine — ** The `scrapyard.projects.allocation_engine` module provides a reusable core for dynamically allocating resources based on availability and capacity constraints, supporting flexible scheduling in com

### PART-META-JSON
{
  "name": "allocation_engine",
  "layer": "projects",
  "purpose": "Provides a reusable core for dynamically allocating resources based on availability and capacity constraints, supporting flexible scheduling in com.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: ResourceAssignment(...); Allocator(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.allocation_engine`.",
  "example": "from scrapyard.projects.allocation_engine import *",
  "import_path": "scrapyard.projects.allocation_engine"
}
### END-PART-META
"""
from sqlalchemy import String, DateTime, ForeignKey, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional
import os, logging, tempfile

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class ResourceAssignment:
    resource_id: str
    start_time: datetime
    end_time: datetime

class Allocator:
    def __init__(self):
        self._resource_availability = {}

    def allocate_resource(self, resource_id: str, start: datetime, end: datetime) -> Optional[ResourceAssignment]:
        if not self.check_availability(resource_id, start, end):
            return None
        assignment = ResourceAssignment(resource_id, start, end)
        if resource_id not in self._resource_availability:
            self._resource_availability[resource_id] = []
        self._resource_availability[resource_id].append(assignment)
        logger.info(f"Allocated resource {resource_id} from {start} to {end}")
        return assignment

    def check_availability(self, resource_id: str, start: datetime, end: datetime) -> bool:
        if resource_id in self._resource_availability:
            for assignment in self._resource_availability[resource_id]:
                if start < assignment.end_time and end > assignment.start_time:
                    return False
        logger.info(f"Resource {resource_id} is available from {start} to {end}")
        return True

def _selftest():
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        db_path = os.path.join(temp_dir.name, 'test.db')
        
        class Resource(IntPKModel):
            __tablename__ = 'allocation_engine_resources'
            name: Mapped[str] = mapped_column(String(50), nullable=False)

        class Allocation(IntPKModel):
            __tablename__ = 'allocations'
            resource_id: Mapped[int] = mapped_column(ForeignKey('allocation_engine_resources.id'), nullable=False)
            start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
            end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            Resource.metadata.create_all(engine)
            Allocation.metadata.create_all(engine)

            session = Session(bind=engine)
            try:
                resource = Resource(name='TestResource')
                session.add(resource)
                session.commit()
                session.refresh(resource)

                allocator = Allocator()
                
                start_time = datetime.now(timezone.utc) - timedelta(hours=1)
                end_time = datetime.now(timezone.utc)
                
                assert allocator.check_availability(str(resource.id), start_time, end_time) is True
                assignment = allocator.allocate_resource(str(resource.id), start_time, end_time)
                assert assignment is not None, "Allocation failed"
                
                assert allocator.check_availability(str(resource.id), start_time, end_time) is False
                
                overlap_start = start_time + timedelta(minutes=30)
                overlap_end = end_time + timedelta(minutes=30)
                assert allocator.check_availability(str(resource.id), overlap_start, overlap_end) is False
                
                future_start = end_time + timedelta(hours=1)
                future_end = future_start + timedelta(hours=1)
                assert allocator.check_availability(str(resource.id), future_start, future_end) is True
                
            finally:
                session.close()
        finally:
            engine.dispose()
    finally:
        temp_dir.cleanup()

if __name__ == "__main__":
    _selftest()
