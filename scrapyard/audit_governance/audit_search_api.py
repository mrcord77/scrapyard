"""
audit_search_api — Search and paginate audit-log entries.

### PART-META-JSON
{
  "name": "audit_search_api",
  "layer": "audit_governance",
  "purpose": "Query layer over audit logs: search_audit_logs(filters, page, per_page) applies equality filters on non-string columns and case-insensitive substring (ILIKE) matching on string columns with offset/limit pagination; get_log_by_id() fetches a single entry. Uses its own AuditLog model on a local DeclarativeBase (table audit_search_api_audit_log) - it does not query the audit_log_service table.",
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "A configured module-level sessionmaker (set _session_maker or adapt); search_audit_logs({'action': 'login', 'user_id': 1}, page, per_page); get_log_by_id(log_id).",
  "outputs": "Lists of AuditLog ORM rows (or a single row / None).",
  "files_created": [],
  "security_notes": "String filter values are embedded in an ILIKE pattern as %value% - queries stay parameterized (no SQL injection), but user-supplied % and _ wildcards are NOT escaped, so callers exposing this to end users should escape LIKE metacharacters or accept broad matches. Unknown filter keys are silently ignored rather than rejected - validate filter names upstream if strictness matters. No authentication: gate read access to audit data in the composing app. Pagination offset grows linearly; cap per_page for untrusted callers.",
  "ai_usage": "Set the module _session_maker to sessionmaker(bind=engine), then search_audit_logs({'action': 'login'}, 1, 50).",
  "example": "from scrapyard.audit_governance.audit_search_api import search_audit_logs, get_log_by_id",
  "import_path": "scrapyard.audit_governance.audit_search_api"
}
### END-PART-META
"""
from sqlalchemy import String, Integer, JSON, DateTime, func, select, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from typing import Optional, List, Dict, Any
import os
import logging
import tempfile
from datetime import datetime

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class AuditLog(Base):
    __tablename__ = "audit_search_api_audit_log"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[int] = mapped_column(Integer)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now())


_session_maker: Optional[sessionmaker] = None


def _get_session():
    """Get a new session from the configured session maker."""
    if _session_maker is None:
        raise RuntimeError("Session not configured")
    return _session_maker()


def search_audit_logs(filters: Dict[str, Any], page: int, per_page: int) -> List[AuditLog]:
    """Search audit logs with filters and pagination."""
    with _get_session() as session:
        query = select(AuditLog)
        
        for key, value in filters.items():
            if hasattr(AuditLog, key):
                column = getattr(AuditLog, key)
                if isinstance(value, str):
                    query = query.where(column.ilike(f"%{value}%"))
                else:
                    query = query.where(column == value)
        
        offset = (page - 1) * per_page
        query = query.offset(offset).limit(per_page)
        
        results = session.scalars(query).all()
        return list(results)


def get_log_by_id(log_id: int) -> Optional[AuditLog]:
    """Retrieve a single audit log by ID."""
    with _get_session() as session:
        return session.get(AuditLog, log_id)


def _selftest():
    """Offline self-test using temporary SQLite database."""
    global _session_maker
    original_session_maker = _session_maker
    
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            engine = create_engine(f"sqlite:///{db_path}", echo=False)
            
            Base.metadata.create_all(engine)
            
            _session_maker = sessionmaker(bind=engine)
            
            with _get_session() as session:
                log1 = AuditLog(action="login", user_id=1, details={"user": "alice"})
                log2 = AuditLog(action="logout", user_id=1, details={"user": "bob"})
                session.add(log1)
                session.add(log2)
                session.commit()
                id1 = log1.id
            
            results = search_audit_logs({"action": "login"}, 1, 10)
            assert len(results) == 1, f"Expected 1 result for action='login', got {len(results)}"
            assert results[0].action == "login"
            
            results = search_audit_logs({"user_id": 1}, 1, 10)
            assert len(results) == 2, f"Expected 2 results for user_id=1, got {len(results)}"
            
            results = search_audit_logs({}, 1, 1)
            assert len(results) == 1, "Pagination should return 1 item per page"
            
            log = get_log_by_id(id1)
            assert log is not None, "Should find log by id"
            assert log.action == "login"
            
            log = get_log_by_id(99999)
            assert log is None, "Should return None for non-existent id"
            
            logger.info("Self-test passed.")
            
    finally:
        _session_maker = original_session_maker


if __name__ == "__main__":
    _selftest()
