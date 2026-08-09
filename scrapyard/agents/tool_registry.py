"""
tool_registry — Registers and dispatches tools for agent operations, enabling dynamic extension of agent capabilities. Provides a centralized, type-safe, and queryable registry for tool definitions and execution.

### PART-META-JSON
{
  "name": "tool_registry",
  "layer": "agents",
  "purpose": "Registers and dispatches tools for agent operations, enabling dynamic extension of agent capabilities. Provides a centralized, type-safe, and queryable registry for tool definitions and execution.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: register_tool(tool); dispatch_tool(task); ToolModel(...); ToolRegistry(...).",
  "outputs": "Returns: register_tool -> None; dispatch_tool -> Optional[ToolModel].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.tool_registry`.",
  "example": "from scrapyard.agents.tool_registry import *",
  "import_path": "scrapyard.agents.tool_registry"
}
### END-PART-META
"""

from sqlalchemy import String, Text, func, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
from typing import Optional
import logging, tempfile

_logger = logging.getLogger(__name__)

class ToolModel(IntPKModel):
    __tablename__ = 'tool_registry_tools'
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text)

# Module-level engine configuration for standalone functions
_engine = None
_Session = None

def _configure_engine(db_url: str):
    global _engine, _Session
    _engine = create_engine(db_url, future=True)
    _Session = sessionmaker(bind=_engine)
    ToolModel.metadata.create_all(bind=_engine)

def register_tool(tool: ToolModel) -> None:
    if _Session is None:
        raise RuntimeError("Engine not configured. Call _configure_engine first.")
    with _Session() as session:
        session.add(tool)
        session.commit()

def dispatch_tool(task: str) -> Optional[ToolModel]:
    if _Session is None:
        raise RuntimeError("Engine not configured. Call _configure_engine first.")
    with _Session() as session:
        tool = session.execute(
            select(ToolModel).where(ToolModel.name == task)
        ).scalars().first()
        return tool

class ToolRegistry:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.engine = None
        self._session_factory = None
    
    def _initialize_db(self) -> None:
        if not self.engine:
            self.engine = create_engine(self.db_url, future=True)
            self._session_factory = sessionmaker(bind=self.engine)
            ToolModel.metadata.create_all(bind=self.engine)
    
    def _close_db(self) -> None:
        if self.engine:
            self.engine.dispose()
            self.engine = None
            self._session_factory = None
    
    def register_tool(self, tool: ToolModel) -> None:
        if self._session_factory is None:
            raise RuntimeError("Database not initialized")
        with self._session_factory() as session:
            session.add(tool)
            session.commit()

    def dispatch_tool(self, task: str) -> Optional[ToolModel]:
        if self._session_factory is None:
            raise RuntimeError("Database not initialized")
        with self._session_factory() as session:
            tool = session.execute(
                select(ToolModel).where(ToolModel.name == task)
            ).scalars().first()
            return tool

def _selftest():
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    db_url = f'sqlite:///{temp_dir.name}/tool_registry.db'
    
    registry = ToolRegistry(db_url)
    
    # Initialize database
    registry._initialize_db()
    
    # Register a new tool
    new_tool = ToolModel(name="example_tool", description="This is an example tool.")
    registry.register_tool(new_tool)
    
    # Dispatch the task and check if it returns the correct tool
    dispatched_tool = registry.dispatch_tool("example_tool")
    assert dispatched_tool is not None, "Tool was not found after registration."
    
    # Try dispatching a non-existent tool
    non_existent_tool = registry.dispatch_tool("nonexistent_tool")
    assert non_existent_tool is None, "Non-existent tool returned unexpectedly."
    
    # Validate schema and constraints
    with registry._session_factory() as session:
        result = session.execute(select(func.count()).select_from(ToolModel)).scalar()
        assert result == 1, "Database did not contain the expected number of records."
    
    _logger.info("Self-test passed successfully.")
    
    registry._close_db()
    temp_dir.cleanup()

if __name__ == "__main__":
    _selftest()
