"""
comment_thread_manager — Manages creation and retrieval of comment threads on shared artifacts, enabling collaborative feedback and discussion within the client portal.

### PART-META-JSON
{
  "name": "comment_thread_manager",
  "layer": "portal",
  "purpose": "Manages creation and retrieval of comment threads on shared artifacts, enabling collaborative feedback and discussion within the client portal.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_comment_thread(session, artifact_id, user_id); add_comment(session, thread_id, user_id, content); CommentThread(...); Comment(...).",
  "outputs": "Returns: create_comment_thread -> CommentThread; add_comment -> Comment.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.portal.comment_thread_manager`.",
  "example": "from scrapyard.portal.comment_thread_manager import *",
  "import_path": "scrapyard.portal.comment_thread_manager"
}
### END-PART-META
"""

import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import List

from sqlalchemy import DateTime, ForeignKey, String, Text, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class CommentThread(IntPKModel):
    __tablename__ = "comment_threads"
    
    thread_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    artifact_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    comments: Mapped[List["Comment"]] = relationship(back_populates="thread", cascade="all, delete-orphan")


class Comment(IntPKModel):
    __tablename__ = "comments"
    
    comment_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(255), ForeignKey("comment_threads.thread_id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    thread: Mapped["CommentThread"] = relationship(back_populates="comments")


def create_comment_thread(session: Session, artifact_id: str, user_id: str) -> CommentThread:
    """Create a new comment thread linked to a specific artifact and user."""
    thread = CommentThread(
        thread_id=str(uuid.uuid4()),
        artifact_id=artifact_id,
        user_id=user_id,
    )
    session.add(thread)
    session.commit()
    return thread


def add_comment(session: Session, thread_id: str, user_id: str, content: str) -> Comment:
    """Add a comment to an existing thread."""
    stmt = select(CommentThread).where(CommentThread.thread_id == thread_id)
    thread = session.execute(stmt).scalar_one_or_none()
    if thread is None:
        raise ValueError(f"Thread with id {thread_id} not found")
    
    comment = Comment(
        comment_id=str(uuid.uuid4()),
        thread_id=thread_id,
        user_id=user_id,
        content=content,
    )
    session.add(comment)
    session.commit()
    return comment


def _selftest() -> None:
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        IntPKModel.metadata.create_all(engine)
        
        with Session(engine) as session:
            thread = create_comment_thread(session, "artifact-001", "user-001")
            assert isinstance(thread, CommentThread)
            assert thread.thread_id is not None
            assert thread.artifact_id == "artifact-001"
            assert thread.user_id == "user-001"
            assert thread.created_at is not None
            
            stmt = select(CommentThread).where(CommentThread.thread_id == thread.thread_id)
            retrieved_thread = session.execute(stmt).scalar_one()
            assert retrieved_thread.thread_id == thread.thread_id
            
            comment = add_comment(session, thread.thread_id, "user-002", "This is a test comment")
            assert isinstance(comment, Comment)
            assert comment.comment_id is not None
            assert comment.thread_id == thread.thread_id
            assert comment.user_id == "user-002"
            assert comment.content == "This is a test comment"
            assert comment.created_at is not None
            
            stmt2 = select(Comment).where(Comment.comment_id == comment.comment_id)
            retrieved_comment = session.execute(stmt2).scalar_one()
            assert retrieved_comment.content == "This is a test comment"
            
            assert len(retrieved_thread.comments) == 1
            assert retrieved_thread.comments[0].comment_id == comment.comment_id
        
        engine.dispose()


if __name__ == "__main__":
    _selftest()
