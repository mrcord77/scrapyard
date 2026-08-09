"""
access_control — Grants and revokes role-based access rules over resources.

### PART-META-JSON
{
  "name": "access_control",
  "layer": "hr_lite_onboardi",
  "purpose": "Grants and revokes access rules mapping roles to resources, with duplicate-grant idempotency and input validation. Owns the Resource model (table access_control_resources) and uses the canonical Role model owned by scrapyard.hr_lite_onboardi.role_assignments (table role_assignments_roles).",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model", "scrapyard.hr_lite_onboardi.role_assignments"],
  "inputs": "resource_id and role_id positive integers; an engine bound via configure_engine().",
  "outputs": "Persisted AccessRule rows; TypeError/ValueError on invalid ids; silent no-op revoke of missing rules.",
  "files_created": [],
  "security_notes": "This part STORES access rules but performs no authentication itself - guard who may call grant_access/revoke_access, since granting is a privilege-escalation primitive. SQLite does not enforce the role/resource foreign keys unless PRAGMA foreign_keys=ON; validate referenced ids exist when running on SQLite.",
  "ai_usage": "Call configure_engine(engine), then grant_access/revoke_access; query AccessRule for enforcement decisions.",
  "example": "from scrapyard.hr_lite_onboardi.access_control import grant_access, revoke_access",
  "import_path": "scrapyard.hr_lite_onboardi.access_control"
}
### END-PART-META
"""
from sqlalchemy import ForeignKey, create_engine, select, UniqueConstraint, delete, String
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
import os
import logging
import tempfile
from typing import Optional

# Canonical-owner pattern: role_assignments owns the Role model.
from scrapyard.hr_lite_onboardi.role_assignments import Role

logger = logging.getLogger(__name__)

# Module-level engine storage - initialized to None to avoid import side effects
_engine: Optional[object] = None


def configure_engine(engine) -> None:
    """Configure the SQLAlchemy engine for this module."""
    global _engine
    _engine = engine


def get_engine():
    """Retrieve the configured engine."""
    if _engine is None:
        raise RuntimeError("Database engine not configured. Call configure_engine() first.")
    return _engine


class Resource(IntPKModel):
    """Resource registry owned by access_control."""
    __tablename__ = 'access_control_resources'
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class AccessRule(IntPKModel):
    __tablename__ = 'access_rules'

    resource_id: Mapped[int] = mapped_column(ForeignKey("access_control_resources.id"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("role_assignments_roles.id"), nullable=False)
    
    __table_args__ = (
        UniqueConstraint('resource_id', 'role_id', name='uix_access_rule_resource_role'),
    )


def grant_access(resource_id: int, role_id: int) -> None:
    """Grant access to a resource for a role. Duplicate grants are ignored."""
    if not isinstance(resource_id, int) or not isinstance(role_id, int):
        raise TypeError("resource_id and role_id must be integers")
    if resource_id <= 0 or role_id <= 0:
        raise ValueError("resource_id and role_id must be positive integers")
    
    engine = get_engine()
    with Session(engine) as session:
        # Check for existing rule to ignore duplicates
        stmt = select(AccessRule).where(
            AccessRule.resource_id == resource_id,
            AccessRule.role_id == role_id
        )
        existing = session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            return
        
        new_rule = AccessRule(resource_id=resource_id, role_id=role_id)
        session.add(new_rule)
        session.commit()


def revoke_access(resource_id: int, role_id: int) -> None:
    """Revoke access to a resource for a role. Non-existent rules are ignored."""
    if not isinstance(resource_id, int) or not isinstance(role_id, int):
        raise TypeError("resource_id and role_id must be integers")
    if resource_id <= 0 or role_id <= 0:
        raise ValueError("resource_id and role_id must be positive integers")
    
    engine = get_engine()
    with Session(engine) as session:
        stmt = delete(AccessRule).where(
            AccessRule.resource_id == resource_id,
            AccessRule.role_id == role_id
        )
        session.execute(stmt)
        session.commit()


def _selftest():
    """Offline self-test using temporary SQLite database."""
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        db_path = os.path.join(temp_dir.name, 'test.db')
        
        # Create SQLAlchemy engine
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        configure_engine(engine)
        
        # Create tables (including resources and roles due to ForeignKey constraints)
        IntPKModel.metadata.create_all(engine)
        
        # Test grant and persistence
        grant_access(1, 2)
        with Session(engine) as session:
            stmt = select(AccessRule)
            rules = session.execute(stmt).scalars().all()
            assert len(rules) == 1
            assert rules[0].resource_id == 1
            assert rules[0].role_id == 2
        
        # Test duplicate grant is ignored
        grant_access(1, 2)
        with Session(engine) as session:
            stmt = select(AccessRule)
            rules = session.execute(stmt).scalars().all()
            assert len(rules) == 1, "Duplicate grant should not create extra records"
        
        # Test multiple grants
        grant_access(3, 4)
        with Session(engine) as session:
            stmt = select(AccessRule)
            rules = session.execute(stmt).scalars().all()
            assert len(rules) == 2
        
        # Test revoke
        revoke_access(1, 2)
        with Session(engine) as session:
            stmt = select(AccessRule)
            rules = session.execute(stmt).scalars().all()
            assert len(rules) == 1
            assert rules[0].resource_id == 3
        
        # Test revoke non-existent (no error)
        revoke_access(99, 99)
        
        # Test invalid IDs raise ValueError
        try:
            grant_access(0, 1)
            assert False, "Should raise ValueError for resource_id <= 0"
        except ValueError:
            pass
        
        try:
            grant_access(1, -5)
            assert False, "Should raise ValueError for role_id <= 0"
        except ValueError:
            pass
        
        try:
            revoke_access(-1, 1)
            assert False, "Should raise ValueError for resource_id <= 0 in revoke"
        except ValueError:
            pass
        
        logger.info("_selftest passed successfully")
        
    finally:
        # Cleanup
        temp_dir.cleanup()
        global _engine
        _engine = None


if __name__ == "__main__":
    _selftest()
