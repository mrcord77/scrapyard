"""
export_progress_tracker — Track the progress of an ongoing export operation in real-time, providing visibility into the status and performance of data export processes. It ensures consistent state tracking and supports real-ti

### PART-META-JSON
{
  "name": "export_progress_tracker",
  "layer": "data_io",
  "purpose": "Track the progress of an ongoing export operation in real-time, providing visibility into the status and performance of data export processes. It ensures consistent state tracking and supports real-ti",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: update_export_progress(current, total, export_id, session); ExportProgressTracker(...).",
  "outputs": "Returns: update_export_progress -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.data_io.export_progress_tracker`.",
  "example": "from scrapyard.data_io.export_progress_tracker import *",
  "import_path": "scrapyard.data_io.export_progress_tracker"
}
### END-PART-META
"""

from sqlalchemy import select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

class ExportProgressTracker(IntPKModel):
    __tablename__ = 'export_progress'

    id: Mapped[int] = mapped_column(primary_key=True)
    current: Mapped[int]
    total: Mapped[int]
    export_id: Mapped[str]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

def update_export_progress(current: int, total: int, export_id: str, session: Session) -> None:
    """Update the export progress in the database."""
    now = datetime.now(timezone.utc)
    
    stmt = select(ExportProgressTracker).where(ExportProgressTracker.export_id == export_id)
    progress = session.execute(stmt).scalars().first()
    
    if progress is not None:
        progress.current = current
        progress.total = total
        progress.updated_at = now
    else:
        new_progress = ExportProgressTracker(
            current=current,
            total=total,
            export_id=export_id,
            created_at=now,
            updated_at=now
        )
        session.add(new_progress)

def _selftest():
    """Self-test function for offline validation."""
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    db_path = os.path.join(temp_dir.name, 'export_progress.db')
    
    engine = create_engine(f"sqlite:///{db_path}")
    ExportProgressTracker.metadata.create_all(engine)

    with Session(engine) as session:
        tracker = ExportProgressTracker(
            current=0, 
            total=100, 
            export_id='test_export',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(tracker)
        session.commit()

        update_export_progress(current=50, total=100, export_id='test_export', session=session)
        session.commit()

        result = session.execute(
            select(ExportProgressTracker).where(ExportProgressTracker.export_id == 'test_export')
        ).scalars().first()
        
        assert result.current == 50 and result.total == 100

    temp_dir.cleanup()

if __name__ == "__main__":
    _selftest()
