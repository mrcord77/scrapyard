"""
workflow_engine — Manage article workflow states through transitions between draft, review, and published states. Enables structured content lifecycle management with auditability and access control.

### PART-META-JSON
{
  "name": "workflow_engine",
  "layer": "knowledge",
  "purpose": "Manage article workflow states through transitions between draft, review, and published states. Enables structured content lifecycle management with auditability and access control.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure(engine); register_user_role(user_id, role); submit_for_review(article_id, user_id); publish_article(article_id, user_id); get_workflow_status(article_id); WorkflowState(...); WorkflowTransition(...).",
  "outputs": "Returns: submit_for_review -> WorkflowState; publish_article -> WorkflowState; get_workflow_status -> WorkflowState.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.knowledge.workflow_engine`.",
  "example": "from scrapyard.knowledge.workflow_engine import *",
  "import_path": "scrapyard.knowledge.workflow_engine"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, DateTime, select, Index, UniqueConstraint, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, Dict
import os
import tempfile
import logging

logger = logging.getLogger(__name__)

# Module-level configuration
_engine = None
_Session = sessionmaker()
_user_roles: Dict[int, str] = {}


class WorkflowState(IntPKModel):
    """Represents a workflow state record for an article (audit trail)."""
    __tablename__ = "workflow_state"
    
    article_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    
    __table_args__ = (
        Index('ix_workflow_state_article_timestamp', 'article_id', 'timestamp'),
    )


class WorkflowTransition(IntPKModel):
    """Defines allowed workflow transitions and required roles."""
    __tablename__ = "workflow_transition"
    
    from_state: Mapped[str] = mapped_column(String(50), nullable=False)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    allowed_role: Mapped[str] = mapped_column(String(50), nullable=False)
    
    __table_args__ = (
        UniqueConstraint('from_state', 'to_state', 'allowed_role', name='uq_transition_role'),
    )


def configure(engine):
    """Configure the workflow engine with a SQLAlchemy engine."""
    global _engine, _Session
    _engine = engine
    _Session = sessionmaker(bind=engine, expire_on_commit=False)
    IntPKModel.metadata.create_all(engine)


def register_user_role(user_id: int, role: str):
    """Register a user's role for permission checking."""
    _user_roles[user_id] = role


def _get_user_role(user_id: int) -> Optional[str]:
    """Get the role for a user."""
    return _user_roles.get(user_id)


def _get_current_state(session: Session, article_id: int) -> Optional[WorkflowState]:
    """Get the most recent workflow state for an article."""
    stmt = select(WorkflowState).where(
        WorkflowState.article_id == article_id
    ).order_by(WorkflowState.timestamp.desc()).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def _validate_transition(session: Session, from_state: str, to_state: str, user_id: int):
    """Validate that a transition is allowed for the user."""
    user_role = _get_user_role(user_id)
    if user_role is None:
        raise ValueError(f"No role configured for user {user_id}")
    
    stmt = select(WorkflowTransition).where(
        WorkflowTransition.from_state == from_state,
        WorkflowTransition.to_state == to_state,
        WorkflowTransition.allowed_role == user_role
    )
    result = session.execute(stmt).scalar_one_or_none()
    if result is None:
        # Check if any transition exists between these states (regardless of role)
        stmt_check = select(WorkflowTransition).where(
            WorkflowTransition.from_state == from_state,
            WorkflowTransition.to_state == to_state
        )
        any_exists = session.execute(stmt_check).scalar_one_or_none()
        if any_exists:
            raise ValueError(
                f"User {user_id} with role '{user_role}' is not authorized for transition "
                f"'{from_state}' -> '{to_state}'"
            )
        else:
            raise ValueError(
                f"Invalid state transition: '{from_state}' -> '{to_state}'"
            )


def submit_for_review(article_id: int, user_id: int) -> WorkflowState:
    """Submit an article for review (draft -> review)."""
    if _engine is None:
        raise RuntimeError("Workflow engine not configured. Call configure() first.")
    
    with _Session() as session:
        current = _get_current_state(session, article_id)
        current_state = current.state if current else "draft"
        
        _validate_transition(session, current_state, "review", user_id)
        
        new_state = WorkflowState(
            article_id=article_id,
            state="review",
            user_id=user_id,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(new_state)
        session.commit()
        session.expunge(new_state)
        return new_state


def publish_article(article_id: int, user_id: int) -> WorkflowState:
    """Publish an article (review -> published)."""
    if _engine is None:
        raise RuntimeError("Workflow engine not configured. Call configure() first.")
    
    with _Session() as session:
        current = _get_current_state(session, article_id)
        if current is None:
            # No workflow history exists, treat as draft
            current_state = "draft"
        else:
            current_state = current.state
        
        _validate_transition(session, current_state, "published", user_id)
        
        new_state = WorkflowState(
            article_id=article_id,
            state="published",
            user_id=user_id,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(new_state)
        session.commit()
        session.expunge(new_state)
        return new_state


def get_workflow_status(article_id: int) -> WorkflowState:
    """Get the current workflow status for an article."""
    if _engine is None:
        raise RuntimeError("Workflow engine not configured. Call configure() first.")
    
    with _Session() as session:
        current = _get_current_state(session, article_id)
        if current is None:
            # Return a transient state representing 'draft' (initial state)
            return WorkflowState(
                article_id=article_id,
                state="draft",
                user_id=0,
                timestamp=datetime.now(timezone.utc)
            )
        session.expunge(current)
        return current


def _selftest():
    """Self test for the workflow engine."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "workflow_test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Configure module
        configure(engine)
        
        # Setup transitions
        with Session(engine) as session:
            session.add(WorkflowTransition(from_state="draft", to_state="review", allowed_role="author"))
            session.add(WorkflowTransition(from_state="review", to_state="published", allowed_role="publisher"))
            session.commit()
        
        # Register test users
        register_user_role(1, "author")
        register_user_role(2, "publisher")
        
        article_id = 1001
        
        # Test: Initial status is draft
        status = get_workflow_status(article_id)
        assert status.state == "draft", f"Expected draft, got {status.state}"
        
        # Test: Submit for review
        review_state = submit_for_review(article_id, user_id=1)
        assert review_state.state == "review"
        assert review_state.article_id == article_id
        assert review_state.user_id == 1
        
        # Verify status updated
        status = get_workflow_status(article_id)
        assert status.state == "review"
        
        # Test: Invalid transition (author cannot publish)
        try:
            publish_article(article_id, user_id=1)
            assert False, "Should have raised error for unauthorized role"
        except ValueError as e:
            assert "not authorized" in str(e)
        
        # Test: Invalid state transition (cannot publish from draft directly)
        article_2 = 1002
        try:
            publish_article(article_2, user_id=2)  # publisher trying to publish draft
            assert False, "Should have raised error for invalid transition"
        except ValueError as e:
            assert "Invalid state transition" in str(e)
        
        # Test: Valid publish by publisher
        published_state = publish_article(article_id, user_id=2)
        assert published_state.state == "published"
        assert published_state.user_id == 2
        
        # Verify final status
        status = get_workflow_status(article_id)
        assert status.state == "published"
        
        # Test: Verify persistence (audit trail)
        with Session(engine) as session:
            states = session.execute(
                select(WorkflowState).where(
                    WorkflowState.article_id == article_id
                ).order_by(WorkflowState.timestamp)
            ).scalars().all()
            assert len(states) == 2
            assert states[0].state == "review"
            assert states[1].state == "published"
        
        logger.info("Workflow engine selftest passed")


if __name__ == "__main__":
    _selftest()
