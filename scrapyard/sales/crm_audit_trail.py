"""
crm_audit_trail — Track changes to CRM entities for auditing and compliance, ensuring full visibility of modifications. This module provides a robust, reusable audit trail system for CRM pipelines.

### PART-META-JSON
{
  "name": "crm_audit_trail",
  "layer": "sales",
  "purpose": "Track changes to CRM entities for auditing and compliance, ensuring full visibility of modifications. This module provides a robust, reusable audit trail system for CRM pipelines.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: log_entity_change(entity_type, entity_id, change); get_audit_trail(entity_id); ChangeLog(...); AuditLog(...).",
  "outputs": "Returns: log_entity_change -> None; get_audit_trail -> List[Dict[str, Any]].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.sales.crm_audit_trail`.",
  "example": "from scrapyard.sales.crm_audit_trail import *",
  "import_path": "scrapyard.sales.crm_audit_trail"
}
### END-PART-META
"""
from sqlalchemy import String, Integer, DateTime, JSON, select, Index, UniqueConstraint, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Any
import os
import logging
import tempfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangeLog:
    entity_type: str
    entity_id: int
    change: dict
    created_at: datetime


class AuditLog(IntPKModel):
    __tablename__ = 'crm_audit_trail_audit_log'
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(Integer)
    change: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_audit_log_entity', 'entity_type', 'entity_id'),
        UniqueConstraint('entity_type', 'entity_id', 'created_at', name='uq_audit_log_unique'),
    )


def log_entity_change(entity_type: str, entity_id: int, change: dict) -> None:
    """Logs a change to the audit trail."""
    with Session() as session:
        session.add(AuditLog(entity_type=entity_type, entity_id=entity_id, change=change))
        session.commit()


def get_audit_trail(entity_id: int) -> List[Dict[str, Any]]:
    """Retrieves full audit history for an entity."""
    query = select(AuditLog).where(AuditLog.entity_id == entity_id).order_by(AuditLog.created_at)
    with Session() as session:
        records = session.scalars(query).all()
        return [
            {
                'id': record.id,
                'entity_type': record.entity_type,
                'entity_id': record.entity_id,
                'change': record.change,
                'created_at': record.created_at,
            }
            for record in records
        ]


def _selftest():
    """Offline self-test function to verify the module's functionality."""
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    db_path = os.path.join(temp_dir.name, 'audit.db')
    
    try:
        engine = create_engine(f"sqlite:///{db_path}")
        AuditLog.metadata.create_all(engine)
        
        global Session
        OriginalSession = Session
        Session = sessionmaker(bind=engine)
        
        try:
            log_entity_change('customer', 123, {'name': 'John Doe', 'email': 'john.doe@example.com'})
            log_entity_change('customer', 456, {'name': 'Jane Smith', 'email': 'jane.smith@example.com'})
            
            trail = get_audit_trail(123)
            assert len(trail) == 1
            assert trail[0]['entity_type'] == 'customer'
            assert trail[0]['entity_id'] == 123
            assert trail[0]['change'] == {'name': 'John Doe', 'email': 'john.doe@example.com'}
            assert 'created_at' in trail[0]
            
            logger.info("_selftest passed successfully")
        finally:
            Session = OriginalSession
            engine.dispose()
    finally:
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
