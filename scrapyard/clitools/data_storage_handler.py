"""
data_storage_handler — Provides SQLite-based data storage for CLI tools, enabling structured data management via SQLAlchemy. Supports database creation, CRUD operations, and table management for common entities.

### PART-META-JSON
{
  "name": "data_storage_handler",
  "layer": "clitools",
  "purpose": "Provides SQLite-based data storage for CLI tools, enabling structured data management via SQLAlchemy. Supports database creation, CRUD operations, and table management for common entities.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "db_path for create_db/DataStorage; ORM objects for add/get/delete; SQL text + bound params for execute_query.",
  "outputs": "Persisted rows in SQLite; ORM instances; execute_query returns list[dict].",
  "files_created": ["<db_path> sqlite database"],
  "security_notes": "execute_query runs caller-supplied SQL: only pass trusted query strings and always bind user values via :params, never string-format them in. Tables are namespaced data_storage_handler_* to avoid metadata collisions on the shared declarative Base.",
  "ai_usage": "Import what you need from `scrapyard.clitools.data_storage_handler`.",
  "example": "from scrapyard.clitools.data_storage_handler import *",
  "import_path": "scrapyard.clitools.data_storage_handler"
}
### END-PART-META
"""
# NOTE: a duplicate pseudo-metadata dict with uppercase keys ("STATUS", ...)
# used to live here; the indexer could not read it. It has been normalized into
# the single canonical PART-META-JSON block above (lowercase "status").
STATUS = "core"

import logging
import os
import tempfile
from typing import Optional, List, Dict, Type

from sqlalchemy import create_engine, text, String, ForeignKey
from sqlalchemy.orm import Session, Mapped, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class User(IntPKModel):
    __tablename__ = "data_storage_handler_users"
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)


class Task(IntPKModel):
    __tablename__ = "data_storage_handler_tasks"
    title: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("data_storage_handler_users.id"))


def create_db(db_path: str) -> None:
    """Create SQLite database and initialize schema."""
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        IntPKModel.metadata.create_all(engine)
    finally:
        engine.dispose()


class DataStorage:
    """Handler for SQLite database operations using SQLAlchemy sessions."""
    
    def __init__(self, db_path: str):
        self.engine = create_engine(f"sqlite:///{db_path}")
    
    def add(self, obj: IntPKModel) -> None:
        """Add an object to the database and commit."""
        with Session(self.engine) as session:
            session.add(obj)
            session.commit()
            session.refresh(obj)
    
    def get(self, model: Type[IntPKModel], id: int) -> Optional[IntPKModel]:
        """Retrieve an object by ID."""
        with Session(self.engine) as session:
            return session.get(model, id)
    
    def delete(self, obj: IntPKModel) -> None:
        """Delete an object from the database."""
        with Session(self.engine) as session:
            attached_obj = session.get(type(obj), obj.id)
            if attached_obj:
                session.delete(attached_obj)
                session.commit()
    
    def execute_query(self, query: str, params: Optional[Dict] = None) -> List[Dict]:
        """Execute arbitrary SQL query and return results as list of dictionaries."""
        with Session(self.engine) as session:
            result = session.execute(text(query), params or {})
            return [dict(row) for row in result.mappings().all()]


def _selftest() -> None:
    """Offline self-test verifying database creation, CRUD, and query execution."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        
        # Test database creation
        create_db(db_path)
        assert os.path.exists(db_path), "Database file not created"
        
        storage = DataStorage(db_path)
        try:
            # Test User insert and retrieve
            user = User(name="Alice", email="alice@example.com")
            storage.add(user)
            assert user.id is not None, "User ID not assigned"
            
            retrieved_user = storage.get(User, user.id)
            assert retrieved_user is not None, "User not retrieved"
            assert retrieved_user.name == "Alice", "User name mismatch"
            assert retrieved_user.email == "alice@example.com", "User email mismatch"
            
            # Test Task insert and retrieve
            task = Task(title="Test Task", description="Test description", user_id=user.id)
            storage.add(task)
            assert task.id is not None, "Task ID not assigned"
            
            retrieved_task = storage.get(Task, task.id)
            assert retrieved_task is not None, "Task not retrieved"
            assert retrieved_task.title == "Test Task", "Task title mismatch"
            assert retrieved_task.user_id == user.id, "Task user_id mismatch"
            
            # Test execute_query
            results = storage.execute_query(
                "SELECT * FROM data_storage_handler_users WHERE id = :id", {"id": user.id}
            )
            assert len(results) == 1, "Query returned wrong count"
            assert results[0]["name"] == "Alice", "Query result mismatch"
            
            # Test delete
            storage.delete(user)
            assert storage.get(User, user.id) is None, "User not deleted"
            
            # Verify task remains (no cascade)
            assert storage.get(Task, task.id) is not None, "Task incorrectly deleted"
            
            storage.delete(task)
            assert storage.get(Task, task.id) is None, "Task not deleted"
            
        finally:
            storage.engine.dispose()
        
        logger.info("_selftest passed")


if __name__ == "__main__":
    _selftest()
