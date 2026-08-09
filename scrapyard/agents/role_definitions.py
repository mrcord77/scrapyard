"""
role_definitions — Define roles and their permissions for agents within the system. Provides a reusable mechanism to model agent access control and responsibilities.

### PART-META-JSON
{
  "name": "role_definitions",
  "layer": "agents",
  "purpose": "Define roles and their permissions for agents within the system. Provides a reusable mechanism to model agent access control and responsibilities.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure_engine(engine); define_role(name, permissions); get_roles(); Role(...).",
  "outputs": "Returns: configure_engine -> None; define_role -> Role; get_roles -> list[Role].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.role_definitions`.",
  "example": "from scrapyard.agents.role_definitions import *",
  "import_path": "scrapyard.agents.role_definitions"
}
### END-PART-META
"""

from sqlalchemy import String, JSON, DateTime, func, select, create_engine, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from typing import Optional, List, Any
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

# Module-level engine reference for database operations
_engine: Optional[Any] = None


class Role(IntPKModel):
    """
    SQLAlchemy ORM model representing an agent role.
    
    Attributes:
        id: Primary key identifier (inherited from IntPKModel).
        name: Unique name of the role.
        permissions: List of permission strings stored as JSON.
        created_at: Timestamp when the role was created.
        updated_at: Timestamp when the role was last updated.
    """
    
    __tablename__ = "role_definitions_roles"
    
    name: Mapped[str] = mapped_column(
        String(255), 
        unique=True, 
        nullable=False, 
        comment="Unique identifier for the role"
    )
    
    permissions: Mapped[List[str]] = mapped_column(
        JSON,
        default=list,
        comment="List of permission strings granted to this role"
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        nullable=False,
        comment="Creation timestamp"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Last modification timestamp"
    )
    
    __table_args__ = (
        UniqueConstraint("name", name="uq_role_name"),
        Index("ix_roles_name", "name"),
    )
    
    def __repr__(self) -> str:
        return f"<Role(id={self.id}, name='{self.name}', permissions={len(self.permissions)})>"


def configure_engine(engine: Any) -> None:
    """
    Configure the database engine for this module.
    
    Args:
        engine: SQLAlchemy Engine instance to use for database operations.
    """
    global _engine
    _engine = engine
    logger.debug(f"Engine configured: {engine}")


def _get_engine() -> Any:
    """
    Retrieve the configured database engine.
    
    Returns:
        The configured SQLAlchemy Engine.
        
    Raises:
        RuntimeError: If no engine has been configured.
    """
    if _engine is None:
        raise RuntimeError(
            "Database engine not configured. Call configure_engine() first."
        )
    return _engine


def define_role(name: str, permissions: list[str]) -> Role:
    """
    Define and persist a new role with the specified name and permissions.
    
    Args:
        name: The unique name identifier for the role. Must be unique across the system.
        permissions: A list of permission strings defining what actions this role can perform.
        
    Returns:
        The newly created Role instance with populated id and timestamps.
        
    Raises:
        ValueError: If a role with the given name already exists.
        RuntimeError: If the database engine has not been configured.
        SQLAlchemyError: If a database error occurs during persistence.
    """
    engine = _get_engine()
    
    with Session(engine) as session:
        # Check for existing role to provide clear error message
        existing = session.execute(
            select(Role).where(Role.name == name)
        ).scalar_one_or_none()
        
        if existing is not None:
            raise ValueError(f"Role with name '{name}' already exists")
        
        # Create new role instance
        role = Role(
            name=name,
            permissions=list(permissions)  # Ensure we store a copy
        )
        
        session.add(role)
        session.commit()
        
        # Refresh to load server-generated defaults (created_at, updated_at, id)
        session.refresh(role)
        
        # Expunge so the instance can be used outside the session
        session.expunge(role)
        
        logger.debug(f"Created role: {role}")
        return role


def get_roles() -> list[Role]:
    """
    Retrieve all defined roles from the database.
    
    Returns:
        A list of all Role instances currently persisted in the database.
        Returns an empty list if no roles are defined.
        
    Raises:
        RuntimeError: If the database engine has not been configured.
    """
    engine = _get_engine()
    
    with Session(engine) as session:
        result = session.execute(select(Role)).scalars().all()
        
        # Expunge all results so they can be used outside the session
        roles = list(result)
        for role in roles:
            session.expunge(role)
            
        logger.debug(f"Retrieved {len(roles)} roles")
        return roles


def _selftest() -> None:
    """
    Execute offline self-tests to verify module functionality.
    
    Creates a temporary SQLite database to test:
    - Role creation and persistence
    - Permission storage as JSON lists
    - Duplicate name rejection
    - Retrieval of all roles
    
    Uses tempfile.TemporaryDirectory for isolation and cleans up all resources.
    """
    global _engine
    original_engine = _engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "selftest_roles.db")
        test_engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            future=True
        )
        
        try:
            # Configure module to use test engine
            configure_engine(test_engine)
            
            # Create all tables
            Role.metadata.create_all(test_engine)
            
            # Test 1: define_role creates role with correct attributes
            admin_perms = ["read:all", "write:all", "delete:all", "execute:all"]
            admin_role = define_role("administrator", admin_perms)
            
            assert admin_role.id is not None, "Role should have an ID after creation"
            assert admin_role.name == "administrator", "Role name should match input"
            assert isinstance(admin_role.permissions, list), "Permissions should be a list"
            assert admin_role.permissions == admin_perms, "Permissions should match input"
            assert len(admin_role.permissions) == 4, "Should have 4 permissions"
            assert isinstance(admin_role.created_at, datetime), "Should have creation timestamp"
            
            # Test 2: get_roles returns all defined roles
            user_perms = ["read:own", "write:own"]
            user_role = define_role("standard_user", user_perms)
            
            all_roles = get_roles()
            assert len(all_roles) == 2, "Should return exactly 2 roles"
            
            role_names = {r.name for r in all_roles}
            assert role_names == {"administrator", "standard_user"}, "Should contain both role names"
            
            # Verify permissions are correctly stored and retrieved
            retrieved_admin = next(r for r in all_roles if r.name == "administrator")
            retrieved_user = next(r for r in all_roles if r.name == "standard_user")
            
            assert "delete:all" in retrieved_admin.permissions, "Admin should have delete permission"
            assert "read:own" in retrieved_user.permissions, "User should have read:own permission"
            assert "delete:all" not in retrieved_user.permissions, "User should not have admin delete permission"
            
            # Test 3: Duplicate role names are rejected
            try:
                define_role("administrator", ["some", "other", "perms"])
                assert False, "Should have raised ValueError for duplicate role name"
            except ValueError as e:
                assert "already exists" in str(e), f"Unexpected error message: {e}"
            
            # Verify no new role was created
            all_roles_after = get_roles()
            assert len(all_roles_after) == 2, "Should still have exactly 2 roles after duplicate attempt"
            
            # Test 4: Empty permissions list works
            empty_role = define_role("empty_role", [])
            assert empty_role.permissions == [], "Empty permissions should be stored as empty list"
            assert len(empty_role.permissions) == 0, "Empty role should have 0 permissions"
            
            logger.info("All self-tests passed successfully")
            
        finally:
            # Restore original engine
            _engine = original_engine
            # Dispose test engine to close connections
            test_engine.dispose()


if __name__ == "__main__":
    _selftest()
