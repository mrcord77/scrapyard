"""
import_progress_tracker — Track real-time import progress with database persistence and flexible update mechanisms, enabling monitoring and control of data import/export workflows.

### PART-META-JSON
{
  "name": "import_progress_tracker",
  "layer": "data_io",
  "purpose": "Track real-time import progress with database persistence and flexible update mechanisms, enabling monitoring and control of data import/export workflows.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: ProgressTracker(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.data_io.import_progress_tracker`.",
  "example": "from scrapyard.data_io.import_progress_tracker import *",
  "import_path": "scrapyard.data_io.import_progress_tracker"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, Float, DateTime, Index, create_engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
import os, logging, tempfile

logger = logging.getLogger(__name__)

class ProgressTracker(IntPKModel):
    """Track real-time import progress with database persistence and flexible updates."""
    __tablename__ = 'import_progress'
    
    operation_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        default=lambda: datetime.now(timezone.utc)
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="ongoing")

    __table_args__ = (
        Index('idx_import_progress_operation_id', 'operation_id'),
    )

    def update_progress(self, current: int, total: int) -> None:
        """Update progress metrics and status.
        
        Updates current, total, percent, timestamp, and status atomically.
        Status transitions to "complete" when current >= total.
        
        Args:
            current: Current progress count
            total: Total expected count
        """
        self.current = current
        self.total = total
        if total > 0:
            self.percent = (current / total) * 100
        else:
            self.percent = 0.0
        self.timestamp = datetime.now(timezone.utc)
        
        if current >= total:
            self.status = "complete"
        else:
            self.status = "ongoing"
        
        logger.debug(f"Progress updated for operation {self.operation_id}: {self.percent:.2f}% ({self.status})")


# Maintain backward compatibility with existing draft naming
ImportProgress = ProgressTracker


def _selftest():
    """Offline self-test with temporary SQLite database."""
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    db_path = os.path.join(temp_dir.name, 'test.db')
    
    engine = None
    try:
        # Setup SQLAlchemy engine and session
        engine = create_engine(f'sqlite:///{db_path}', echo=False)
        Session = sessionmaker(bind=engine)
        
        # Create tables
        IntPKModel.metadata.create_all(engine)

        session = Session()
        
        # Test creation and persistence
        tracker1 = ProgressTracker(operation_id='test_op_1')
        session.add(tracker1)
        session.commit()
        
        assert tracker1.id is not None, "ID should be set after commit"
        assert tracker1.status == "ongoing", "Initial status should be ongoing"
        
        # Update progress
        tracker1.update_progress(current=50, total=100)
        session.commit()
        
        # Check if update was persisted correctly
        session.refresh(tracker1)
        assert tracker1.percent == 50.0, f"Percent should be 50.0 after updating, got {tracker1.percent}"
        assert tracker1.current == 50, "Current should be 50"
        assert tracker1.total == 100, "Total should be 100"
        assert tracker1.status == "ongoing", "Status should be ongoing at 50%"
        
        # Test status transition to complete on final update
        tracker1.update_progress(current=100, total=100)
        session.commit()
        session.refresh(tracker1)
        assert tracker1.status == "complete", "Status should transition to complete when current == total"
        assert tracker1.percent == 100.0, "Percent should be 100.0 when complete"
        
        # Test multiple trackers for the same operation_id (no unique constraint violation)
        tracker2 = ProgressTracker(operation_id='test_op_1')
        session.add(tracker2)
        session.commit()
        
        assert tracker2.id is not None, "Second tracker should have ID"
        assert tracker2.id != tracker1.id, "ID should be different for the same operation_id"
        
        # Verify both trackers exist in database
        trackers = session.query(ProgressTracker).filter_by(operation_id='test_op_1').all()
        assert len(trackers) == 2, f"Should have 2 trackers for operation_id 'test_op_1', got {len(trackers)}"
        
        # Test transactional rollback safety
        tracker3 = ProgressTracker(operation_id='rollback_test')
        session.add(tracker3)
        session.rollback()
        
        # Verify tracker3 was not persisted
        result = session.query(ProgressTracker).filter_by(operation_id='rollback_test').first()
        assert result is None, "Rolled back tracker should not exist in database"
        
        # Test zero division handling
        tracker4 = ProgressTracker(operation_id='zero_test')
        tracker4.update_progress(current=0, total=0)
        session.add(tracker4)
        session.commit()
        assert tracker4.percent == 0.0, "Percent should be 0.0 when total is 0"
        assert tracker4.status == "complete", "Status should be complete when current >= total (0 >= 0)"
        
        session.close()
        engine.dispose()
        
    finally:
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
