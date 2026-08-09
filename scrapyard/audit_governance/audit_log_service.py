"""
audit_log_service — Append-only audit logging with filtered retrieval.

### PART-META-JSON
{
  "name": "audit_log_service",
  "layer": "audit_governance",
  "purpose": "Append-only audit logging service: log_action() persists action name, user id, arbitrary JSON details, and a UTC timestamp; get_logs() retrieves entries filtered by action, user_id, and created_after/created_before time bounds, newest first. The API exposes no update or delete path, keeping entries immutable at the service level.",
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure(session_factory) once at startup; log_action(action, user_id, details_dict); get_logs({'action': ..., 'user_id': ..., 'created_after': dt, 'created_before': dt}).",
  "outputs": "AuditLog ORM rows (audit_log_service_audit_log table); get_logs returns a list ordered by created_at desc.",
  "files_created": [],
  "security_notes": "The details dict is stored verbatim as JSON - callers MUST NOT put secrets, tokens, or raw PII in it; this service does no scrubbing. Immutability is enforced only at this API surface: anyone with direct DB access can still alter rows, so for tamper-evident audit pair it with DB permissions or hash-chaining. Failed writes roll back and re-raise so audit gaps are loud, not silent. No authentication: the composing app decides who may write or read logs.",
  "ai_usage": "configure(sessionmaker(bind=engine)); log_action('user.login', uid, {'ip': ip}); get_logs({'user_id': uid}).",
  "example": "from scrapyard.audit_governance.audit_log_service import configure, log_action, get_logs",
  "import_path": "scrapyard.audit_governance.audit_log_service"
}
### END-PART-META
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Callable
import logging
import tempfile
import os

from sqlalchemy import String, Integer, DateTime, JSON, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

_session_factory: Optional[Callable[[], Session]] = None


class AuditLog(IntPKModel):
    """Audit log entry model. Immutable once committed."""
    
    __tablename__ = "audit_log_service_audit_log"
    
    action: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )


def configure(session_factory: Callable[[], Session]) -> None:
    """Configure the audit log service with a session factory."""
    global _session_factory
    _session_factory = session_factory
    logger.debug("Audit log service configured")


def _get_session() -> Session:
    """Get a session from the configured factory."""
    if _session_factory is None:
        raise RuntimeError(
            "Audit log service not configured. Call configure() with a session factory."
        )
    return _session_factory()


def log_action(action: str, user_id: int, details: dict) -> None:
    """
    Log an action with user context and arbitrary details.
    
    Args:
        action: The action type/name
        user_id: The ID of the user performing the action  
        details: Arbitrary dictionary of additional context
    """
    session = _get_session()
    try:
        entry = AuditLog(
            action=action,
            user_id=user_id,
            details=details,
            created_at=datetime.now(timezone.utc)
        )
        session.add(entry)
        session.commit()
        logger.debug(f"Logged action '{action}' for user {user_id}")
    except Exception:
        session.rollback()
        logger.exception(f"Failed to log action '{action}' for user {user_id}")
        raise
    finally:
        session.close()


def get_logs(filters: dict) -> List[AuditLog]:
    """
    Retrieve audit logs with optional filtering.
    
    Supported filters:
        action: str - exact match on action name
        user_id: int - exact match on user ID  
        created_after: datetime - logs created at or after this time
        created_before: datetime - logs created at or before this time
    
    Args:
        filters: Dictionary of filter criteria
        
    Returns:
        List of AuditLog entries matching filters, ordered by created_at desc
    """
    session = _get_session()
    try:
        stmt = select(AuditLog)
        
        if "action" in filters:
            stmt = stmt.where(AuditLog.action == filters["action"])
        if "user_id" in filters:
            stmt = stmt.where(AuditLog.user_id == filters["user_id"])
        if "created_after" in filters:
            stmt = stmt.where(AuditLog.created_at >= filters["created_after"])
        if "created_before" in filters:
            stmt = stmt.where(AuditLog.created_at <= filters["created_before"])
            
        stmt = stmt.order_by(AuditLog.created_at.desc())
        result = session.execute(stmt)
        return list(result.scalars().all())
    finally:
        session.close()


def _selftest() -> None:
    """Self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "audit_test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
        
        IntPKModel.metadata.create_all(engine)
        
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        configure(factory)
        
        try:
            # Test empty state
            assert len(get_logs({})) == 0, "Database should start empty"
            
            # Test log_action stores data
            log_action("user.login", 1, {"ip": "127.0.0.1"})
            log_action("user.logout", 1, {"ip": "127.0.0.1"})
            log_action("user.login", 2, {"ip": "192.168.1.1"})
            
            all_logs = get_logs({})
            assert len(all_logs) == 3, f"Expected 3 logs, got {len(all_logs)}"
            
            # Test action filter
            logins = get_logs({"action": "user.login"})
            assert len(logins) == 2, f"Expected 2 login logs, got {len(logins)}"
            assert all(l.action == "user.login" for l in logins)
            
            # Test user_id filter
            user1 = get_logs({"user_id": 1})
            assert len(user1) == 2, f"Expected 2 logs for user 1, got {len(user1)}"
            
            # Test combined filters
            combined = get_logs({"action": "user.login", "user_id": 2})
            assert len(combined) == 1
            assert combined[0].details == {"ip": "192.168.1.1"}
            
            # Test time range filters
            now = datetime.now(timezone.utc)
            past = now - timedelta(hours=1)
            future = now + timedelta(hours=1)
            
            assert len(get_logs({"created_after": past})) == 3
            assert len(get_logs({"created_after": future})) == 0
            assert len(get_logs({"created_before": past})) == 0
            assert len(get_logs({"created_before": future})) == 3
            
            # Test immutability - verify API provides no update path
            # and objects are properly persisted
            first = all_logs[0]
            retrieved = get_logs({"user_id": first.user_id})
            assert any(r.id == first.id for r in retrieved)
            
            # Verify model structure
            assert AuditLog.__tablename__ == "audit_log_service_audit_log"
            assert hasattr(AuditLog, "id")
            assert hasattr(AuditLog, "action") 
            assert hasattr(AuditLog, "user_id")
            assert hasattr(AuditLog, "details")
            assert hasattr(AuditLog, "created_at")
            
        finally:
            engine.dispose()
            global _session_factory
            _session_factory = None


if __name__ == "__main__":
    _selftest()
