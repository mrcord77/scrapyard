"""
dependency_tracker — Tracks cross-project dependencies in the workspace. Enables analysis of interdependencies between projects, modules, and libraries.

### PART-META-JSON
{
  "name": "dependency_tracker",
  "layer": "factory_intel",
  "purpose": "Tracks cross-project dependencies in the workspace. Enables analysis of interdependencies between projects, modules, and libraries.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: scan_imports(project_dir); track_dependencies(session, project_id, project_dir, module_map); Dependency(...); DependencyTracker(...).",
  "outputs": "Returns: scan_imports -> Set[str]; track_dependencies -> List[Tuple[int, int]].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.factory_intel.dependency_tracker`.",
  "example": "from scrapyard.factory_intel.dependency_tracker import *",
  "import_path": "scrapyard.factory_intel.dependency_tracker"
}
### END-PART-META
"""
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import (
    Integer,
    String,
    DateTime,
    UniqueConstraint,
    select,
    delete,
    and_,
    create_engine,
)
from sqlalchemy.orm import Mapped, mapped_column, Session

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class Dependency(IntPKModel):
    """ORM model for tracking dependencies between projects."""
    
    __tablename__ = "dependency_tracker_dependencies"
    
    source_project_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    target_project_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    dependency_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, default="import"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    
    __table_args__ = (
        UniqueConstraint(
            "source_project_id", 
            "target_project_id", 
            name="uix_dependency_pair"
        ),
    )


def scan_imports(project_dir: str) -> Set[str]:
    """AST-scan every .py file under project_dir; return top-level imported module names."""
    import ast

    modules: Set[str] = set()
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", ".venv", "node_modules"}]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    tree = ast.parse(f.read(), filename=path)
            except (SyntaxError, OSError) as e:
                logger.debug("skipping unparseable file %s: %s", path, e)
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        modules.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.level == 0:  # skip relative imports
                        modules.add(node.module.split(".")[0])
    return modules


def track_dependencies(
    session: Session,
    project_id: int,
    project_dir: str,
    module_map: Optional[Dict[str, int]] = None,
) -> List[Tuple[int, int]]:
    """
    Track dependencies for a specific project by AST-scanning its source tree.

    Walks project_dir, extracts top-level imported module names via `ast`,
    maps each name to a known project id via module_map (module name ->
    project id, e.g. built from the projects table), and records the
    resulting (source, target) edges in the dependencies table.

    Returns the list of recorded (source_project_id, target_project_id) edges.
    """
    logger.debug("Tracking dependencies for project %s from %s", project_id, project_dir)
    if not os.path.isdir(project_dir):
        raise NotADirectoryError(f"project_dir does not exist: {project_dir}")

    imported = scan_imports(project_dir)
    module_map = module_map or {}
    tracker = DependencyTracker(session)
    edges: List[Tuple[int, int]] = []
    for mod in sorted(imported):
        target_id = module_map.get(mod)
        if target_id is None or target_id == project_id:
            continue  # unknown/external module, or self-import
        tracker.add_dependency(project_id, target_id, "import")
        edges.append((project_id, target_id))
    session.flush()
    return edges


class DependencyTracker:
    """
    High-level API for dependency tracking and analysis across projects.
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    def add_dependency(
        self, 
        source_id: int, 
        target_id: int, 
        dep_type: Optional[str] = None
    ) -> Dependency:
        """Add or update a dependency relationship between two projects."""
        existing = self.session.scalar(
            select(Dependency).where(
                and_(
                    Dependency.source_project_id == source_id,
                    Dependency.target_project_id == target_id,
                )
            )
        )
        
        if existing:
            existing.updated_at = datetime.now(timezone.utc)
            if dep_type:
                existing.dependency_type = dep_type
            return existing
        
        dep = Dependency(
            source_project_id=source_id,
            target_project_id=target_id,
            dependency_type=dep_type or "import",
        )
        self.session.add(dep)
        self.session.flush()
        return dep
    
    def remove_dependency(self, source_id: int, target_id: int) -> bool:
        """Remove a specific dependency relationship."""
        result = self.session.execute(
            delete(Dependency).where(
                and_(
                    Dependency.source_project_id == source_id,
                    Dependency.target_project_id == target_id,
                )
            )
        )
        return result.rowcount > 0
    
    def get_dependencies(self, project_id: int) -> List[Dependency]:
        """Get all outgoing dependencies for a project (what it depends on)."""
        return list(
            self.session.scalars(
                select(Dependency).where(
                    Dependency.source_project_id == project_id
                )
            )
        )
    
    def get_dependents(self, project_id: int) -> List[Dependency]:
        """Get all incoming dependencies to a project (what depends on it)."""
        return list(
            self.session.scalars(
                select(Dependency).where(
                    Dependency.target_project_id == project_id
                )
            )
        )
    
    def update_project_dependencies(
        self, 
        project_id: int, 
        targets: List[Tuple[int, Optional[str]]]
    ) -> None:
        """
        Atomic update of all dependencies for a project.
        Removes dependencies not in targets, adds new ones, preserves existing.
        """
        current_deps = {
            (d.target_project_id, d.dependency_type)
            for d in self.get_dependencies(project_id)
        }
        new_deps = set(targets)
        
        # Remove obsolete dependencies
        for target_id, _ in current_deps - new_deps:
            self.remove_dependency(project_id, target_id)
        
        # Add new dependencies
        for target_id, dep_type in new_deps - current_deps:
            self.add_dependency(project_id, target_id, dep_type)
        
        self.session.flush()
    
    def find_circular_dependencies(self) -> List[List[int]]:
        """Detect circular dependency chains using DFS."""
        deps = self.session.scalars(select(Dependency)).all()
        
        # Build adjacency list
        graph: Dict[int, Set[int]] = {}
        for d in deps:
            graph.setdefault(d.source_project_id, set()).add(d.target_project_id)
        
        cycles: List[List[int]] = []
        visited: Set[int] = set()
        rec_stack: Set[int] = set()
        
        def dfs(node: int, path: List[int]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, path)
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])
            
            path.pop()
            rec_stack.remove(node)
        
        for node in list(graph.keys()):
            if node not in visited:
                dfs(node, [])
        
        return cycles


def _selftest() -> bool:
    """Offline self-test with temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_deps.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        
        try:
            with Session(engine) as session:
                tracker = DependencyTracker(session)
                
                # Test: Create and query dependency records
                dep1 = tracker.add_dependency(1, 2, "import")
                dep2 = tracker.add_dependency(1, 3, "uses")
                dep3 = tracker.add_dependency(2, 3, "import")
                session.commit()
                
                assert dep1.source_project_id == 1
                assert dep1.target_project_id == 2
                assert isinstance(dep1.id, int)
                
                # Test: Query dependencies across multiple projects
                deps_proj1 = tracker.get_dependencies(1)
                assert len(deps_proj1) == 2
                targets = {d.target_project_id for d in deps_proj1}
                assert targets == {2, 3}
                
                # Test: Query dependents
                dependents_proj3 = tracker.get_dependents(3)
                assert len(dependents_proj3) == 2
                
                # Test: Update without data corruption
                tracker.update_project_dependencies(
                    1, [(2, "import"), (4, "requires")]
                )
                session.commit()
                
                updated_deps = tracker.get_dependencies(1)
                assert len(updated_deps) == 2
                target_ids = {d.target_project_id for d in updated_deps}
                assert target_ids == {2, 4}
                assert not any(d.target_project_id == 3 for d in updated_deps)
                
                # Test: Circular dependency detection
                tracker.add_dependency(3, 1)  # Creates 1->2->3->1 cycle
                session.commit()
                cycles = tracker.find_circular_dependencies()
                assert len(cycles) > 0
                # Verify the cycle contains our expected nodes
                flat_cycles = [node for cycle in cycles for node in cycle]
                assert 1 in flat_cycles and 2 in flat_cycles and 3 in flat_cycles
                
                # Test: track_dependencies performs a REAL AST import scan
                proj_dir = os.path.join(tmpdir, "proj_a")
                os.makedirs(proj_dir)
                with open(os.path.join(proj_dir, "app.py"), "w", encoding="utf-8") as f:
                    f.write("import lib_b\nfrom lib_c.sub import thing\nimport os\n")
                edges = track_dependencies(
                    session, 10, proj_dir,
                    module_map={"lib_b": 20, "lib_c": 30},
                )
                session.commit()
                assert set(edges) == {(10, 20), (10, 30)}, edges
                scanned = {d.target_project_id for d in tracker.get_dependencies(10)}
                assert scanned == {20, 30}  # 'os' (unmapped/external) excluded
                assert scan_imports(proj_dir) >= {"lib_b", "lib_c", "os"}

                # Test: Idempotency - adding same dep twice doesn't duplicate
                initial_count = len(tracker.get_dependencies(2))
                tracker.add_dependency(2, 3, "import")  # Already exists
                session.commit()
                final_count = len(tracker.get_dependencies(2))
                assert initial_count == final_count
                
        finally:
            engine.dispose()

    print("dependency_tracker selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
