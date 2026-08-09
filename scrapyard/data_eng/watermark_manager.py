"""
watermark_manager — Manage watermarks for incremental data sync, ensuring only new or updated records are processed. It tracks and updates the latest processed position for data sources.

### PART-META-JSON
{
  "name": "watermark_manager",
  "layer": "data_eng",
  "purpose": "Manage watermarks for incremental data sync, ensuring only new or updated records are processed. It tracks and updates the latest processed position for data sources.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: Base(...); WatermarkTable(...); WatermarkManager(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.data_eng.watermark_manager`.",
  "example": "from scrapyard.data_eng.watermark_manager import *",
  "import_path": "scrapyard.data_eng.watermark_manager"
}
### END-PART-META
"""
from dataclasses import dataclass
from sqlalchemy import String, JSON, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session, DeclarativeBase
from typing import Optional, Any
import os, logging, tempfile

logger = logging.getLogger(__name__)

PART_NAME = "watermark_manager"
LAYER = "data_eng"

class Base(DeclarativeBase):
    pass

class WatermarkTable(Base):
    __tablename__ = 'watermark_table'
    source_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    watermark_value: Mapped[Any] = mapped_column(JSON)

@dataclass
class WatermarkManager:
    session: Session

    def update_watermark(self, source_id: str, new_watermark: Any) -> None:
        """
        Update the watermark for a given source ID.
        :param source_id: The unique identifier of the data source.
        :param new_watermark: The new watermark value to be set.
        """
        stmt = select(WatermarkTable).where(WatermarkTable.source_id == source_id)
        existing = self.session.execute(stmt).scalar_one_or_none()
        
        if not existing:
            self.session.add(WatermarkTable(source_id=source_id, watermark_value=new_watermark))
        else:
            existing.watermark_value = new_watermark
        self.session.commit()

    def get_latest_watermark(self, source_id: str) -> Optional[Any]:
        """
        Retrieve the latest watermark for a given source ID.
        :param source_id: The unique identifier of the data source.
        :return: The latest watermark value or None if not found.
        """
        stmt = select(WatermarkTable).where(WatermarkTable.source_id == source_id)
        result = self.session.execute(stmt).scalar_one_or_none()
        return result.watermark_value if result is not None else None

def _selftest() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_file = os.path.join(temp_dir, 'watermark_test.db')
        engine = create_engine(f"sqlite:///{db_file}", echo=False)
        WatermarkTable.metadata.create_all(engine)
        
        with Session(engine) as session:
            manager = WatermarkManager(session)

            # Create and retrieve watermark for a source
            source_id = "test_source"
            manager.update_watermark(source_id, {"key": "value"})
            assert manager.get_latest_watermark(source_id) == {"key": "value"}

            # Update and verify new watermark value
            manager.update_watermark(source_id, {"new_key": "new_value"})
            assert manager.get_latest_watermark(source_id) == {"new_key": "new_value"}

            # Handle missing source gracefully
            assert manager.get_latest_watermark("nonexistent_source") is None

            # Ensure idempotent updates
            manager.update_watermark(source_id, {"new_key": "new_value"})
            assert manager.get_latest_watermark(source_id) == {"new_key": "new_value"}

        engine.dispose()

if __name__ == "__main__":
    _selftest()
