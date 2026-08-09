"""
user_access — Control access to knowledge base articles using user roles and permissions. Provides fine-grained access management with persistent storage and type-safe operations.

### PART-META-JSON
{
  "name": "user_access",
  "layer": "knowledge",
  "purpose": "Control access to knowledge base articles using user roles and permissions. Provides fine-grained access management with persistent storage and type-safe operations.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "scrapyard.database.base_model",
    "sqlalchemy.orm",
    "sqlalchemy.sql"
  ],
  "inputs": "Public API: configure(engine); grant_access(article_id, user_id, role); check_access(article_id, user_id); revoke_access(article_id, user_id); UserAccess(...).",
  "outputs": "Returns: configure -> None; grant_access -> None; check_access -> bool; revoke_access -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.knowledge.user_access`.",
  "example": "from scrapyard.knowledge.user_access import *",
  "import_path": "scrapyard.knowledge.user_access"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, UniqueConstraint, select, delete, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from sqlalchemy.exc import IntegrityError
from scrapyard.database.base_model import IntPKModel
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

_engine = None


class UserAccess(IntPKModel):
    __tablename__ = "user_access"
    
    article_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(255), nullable=False)
    
    __table_args__ = (
        UniqueConstraint('article_id', 'user_id', 'role', name='unique_user_article_role'),
    )


def configure(engine) -> None:
    """Configure the database engine for the module."""
    global _engine
    _engine = engine


def _get_session() -> Session:
    """Get a new session from the configured engine."""
    if _engine is None:
        raise RuntimeError("Database engine not configured. Call configure() first.")
    return Session(_engine)


def _validate_ids(article_id: int, user_id: int) -> None:
    """Validate that IDs are positive integers."""
    if not isinstance(article_id, int) or article_id <= 0:
        raise ValueError(f"article_id must be a positive integer, got {article_id}")
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError(f"user_id must be a positive integer, got {user_id}")


def grant_access(article_id: int, user_id: int, role: str) -> None:
    """
    Grant access to an article for a user with a specific role.
    Duplicate grants are silently ignored.
    """
    _validate_ids(article_id, user_id)
    if not role or not isinstance(role, str):
        raise ValueError("role must be a non-empty string")
    
    session = _get_session()
    try:
        access = UserAccess(article_id=article_id, user_id=user_id, role=role)
        session.add(access)
        session.commit()
    except IntegrityError:
        # Duplicate entry, ignore as per spec
        session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_access(article_id: int, user_id: int) -> bool:
    """
    Check if a user has any access to an article.
    Returns True if any role exists, False otherwise.
    """
    _validate_ids(article_id, user_id)
    
    session = _get_session()
    try:
        result = session.execute(
            select(UserAccess).where(
                UserAccess.article_id == article_id,
                UserAccess.user_id == user_id
            ).limit(1)
        ).scalar_one_or_none()
        return result is not None
    finally:
        session.close()


def revoke_access(article_id: int, user_id: int) -> None:
    """
    Revoke all access for a user to an article.
    Removes all roles for the user-article pair.
    """
    _validate_ids(article_id, user_id)
    
    session = _get_session()
    try:
        session.execute(
            delete(UserAccess).where(
                UserAccess.article_id == article_id,
                UserAccess.user_id == user_id
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    global _engine
    old_engine = _engine
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            # Create tables
            UserAccess.metadata.create_all(engine)
            configure(engine)
            
            # Test invalid IDs raise exceptions
            try:
                grant_access(-1, 1, "admin")
                assert False, "Should raise for negative article_id"
            except ValueError:
                pass
            
            try:
                grant_access(1, 0, "admin")
                assert False, "Should raise for zero user_id"
            except ValueError:
                pass
            
            # Test grant and check
            grant_access(1, 100, "admin")
            assert check_access(1, 100) is True, "Should have access after grant"
            
            # Test duplicate grants are ignored
            grant_access(1, 100, "admin")  # Should not raise
            assert check_access(1, 100) is True
            
            # Verify duplicate was not created
            session = _get_session()
            count = session.query(UserAccess).filter_by(article_id=1, user_id=100).count()
            session.close()
            assert count == 1, "Duplicate grant should be ignored"
            
            # Test multiple roles per user are handled
            grant_access(1, 100, "editor")
            assert check_access(1, 100) is True
            
            # Verify multiple roles exist
            session = _get_session()
            roles = session.query(UserAccess).filter_by(article_id=1, user_id=100).all()
            session.close()
            assert len(roles) == 2, "Should have two roles"
            
            # Test check returns False for no access
            assert check_access(2, 100) is False, "Different article should return False"
            assert check_access(1, 200) is False, "Different user should return False"
            
            # Test revoke removes all access
            revoke_access(1, 100)
            assert check_access(1, 100) is False, "Should not have access after revoke"
            
            # Verify all roles removed
            session = _get_session()
            count_after = session.query(UserAccess).filter_by(article_id=1, user_id=100).count()
            session.close()
            assert count_after == 0, "All roles should be removed"
            
            # Test revoke on non-existent access does not raise
            revoke_access(999, 999)
            
        finally:
            engine.dispose()
            _engine = old_engine


if __name__ == "__main__":
    _selftest()
