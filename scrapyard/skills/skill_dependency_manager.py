"""
skill_dependency_manager — Manage inter-skill dependency graphs with cycle detection and deterministic resolution order.

### PART-META-JSON
{
  "name": "skill_dependency_manager",
  "layer": "skills",
  "purpose": "Skill dependency graph over SQLAlchemy: add/remove edges, fetch the graph, and resolve_dependencies() returns a deterministic topological execution order, raising CircularDependencyError on cycles.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy"],
  "inputs": "Skill id strings; dependency edges (source depends on target); SQLAlchemy session.",
  "outputs": "Dependency edge rows; topologically sorted skill id lists.",
  "files_created": [],
  "security_notes": "Graph data is trusted configuration - edges determine execution order, so protect writes the same as skill registration. Parameterized ORM access only; no code execution here.",
  "ai_usage": "DependencyManager(session).add_dependency('a','b'); resolve_dependencies(['a']) for run order.",
  "example": "from scrapyard.skills.skill_dependency_manager import DependencyManager, resolve_dependencies",
  "import_path": "scrapyard.skills.skill_dependency_manager"
}
### END-PART-META
"""

from __future__ import annotations

import heapq
import logging
import os
import tempfile
from collections import defaultdict
from typing import Optional

from sqlalchemy import String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class CircularDependencyError(Exception):
    """Raised when a circular dependency is detected while resolving skills."""


class DependencyError(Exception):
    """Raised for generic dependency management errors."""


class DependencyEdge(IntPKModel):
    """A single directed edge in the skill dependency graph."""

    __tablename__ = "dependency_graph"

    skill_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    depends_on_skill_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "skill_id",
            "depends_on_skill_id",
            name="uix_dependency_graph_skill_dependency",
        ),
    )


class DependencyManager:
    """Manage and persist skill dependencies using a SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def add_dependency(self, source: str, target: str) -> None:
        """Record that ``source`` depends on ``target``."""
        if not isinstance(source, str) or not source:
            raise TypeError("source must be a non-empty string")
        if not isinstance(target, str) or not target:
            raise TypeError("target must be a non-empty string")
        if source == target:
            raise CircularDependencyError("a skill cannot depend on itself")

        existing = self._session.execute(
            select(DependencyEdge).where(
                DependencyEdge.skill_id == source,
                DependencyEdge.depends_on_skill_id == target,
            )
        ).scalar_one_or_none()

        if existing is not None:
            logger.debug("Dependency %s -> %s already exists", source, target)
            return

        edge = DependencyEdge(skill_id=source, depends_on_skill_id=target)
        self._session.add(edge)
        self._session.commit()
        logger.debug("Added dependency %s -> %s", source, target)

    def remove_dependency(self, source: str, target: str) -> None:
        """Remove the dependency ``source`` -> ``target``."""
        if not isinstance(source, str) or not source:
            raise TypeError("source must be a non-empty string")
        if not isinstance(target, str) or not target:
            raise TypeError("target must be a non-empty string")

        edge = self._session.execute(
            select(DependencyEdge).where(
                DependencyEdge.skill_id == source,
                DependencyEdge.depends_on_skill_id == target,
            )
        ).scalar_one_or_none()

        if edge is None:
            raise ValueError(f"dependency {source!r} -> {target!r} does not exist")

        self._session.delete(edge)
        self._session.commit()
        logger.debug("Removed dependency %s -> %s", source, target)

    def get_dependency_graph(self) -> dict[str, list[str]]:
        """Return the full dependency graph as skill_id -> list of dependencies."""
        rows = self._session.execute(select(DependencyEdge)).scalars().all()
        graph: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            graph[row.skill_id].append(row.depends_on_skill_id)
        return {skill: sorted(deps) for skill, deps in graph.items()}


def resolve_dependencies(
    skill_ids: list[str],
    *,
    manager: Optional[DependencyManager] = None,
) -> list[str]:
    """Return ``skill_ids`` plus their transitive deps in topological order.

    The returned list is sorted so that every skill appears after all of its
    dependencies.  The sort is deterministic: ties are broken lexicographically.
    """
    if manager is None:
        raise TypeError("a DependencyManager instance is required")
    if not isinstance(skill_ids, list):
        raise TypeError("skill_ids must be a list")

    for sid in skill_ids:
        if not isinstance(sid, str):
            raise TypeError("all skill_ids must be strings")

    graph = manager.get_dependency_graph()

    # Collect the input skills and all transitive dependencies.
    nodes: set[str] = set()
    stack = list(skill_ids)
    while stack:
        current = stack.pop()
        if current in nodes:
            continue
        nodes.add(current)
        for dep in graph.get(current, []):
            if dep not in nodes:
                stack.append(dep)

    if not nodes:
        return []

    # Kahn's algorithm.
    in_degree: dict[str, int] = {node: 0 for node in nodes}
    dependents: dict[str, list[str]] = {node: [] for node in nodes}

    for node in nodes:
        for dep in graph.get(node, []):
            if dep in nodes:
                in_degree[node] += 1
                dependents[dep].append(node)

    ready: list[str] = [
        node for node, degree in in_degree.items() if degree == 0
    ]
    heapq.heapify(ready)

    result: list[str] = []
    while ready:
        node = heapq.heappop(ready)
        result.append(node)
        for dependent in sorted(dependents[node]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                heapq.heappush(ready, dependent)

    if len(result) != len(nodes):
        remaining = sorted(nodes - set(result))
        raise CircularDependencyError(
            f"circular dependency detected involving: {remaining}"
        )

    return result


def _selftest() -> None:
    """Offline self-test for the dependency manager."""
    logger.info("Starting skill_dependency_manager selftest")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_dependency_manager.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)

        try:
            IntPKModel.metadata.create_all(engine)

            with Session(engine) as session:
                manager = DependencyManager(session)

                # Basic add / retrieve
                manager.add_dependency("skill_c", "skill_a")
                manager.add_dependency("skill_c", "skill_b")
                manager.add_dependency("skill_b", "skill_a")

                graph = manager.get_dependency_graph()
                assert "skill_c" in graph
                assert set(graph["skill_c"]) == {"skill_a", "skill_b"}
                assert set(graph["skill_b"]) == {"skill_a"}

                # Topological ordering
                order = resolve_dependencies(["skill_c"], manager=manager)
                assert order.index("skill_a") < order.index("skill_b")
                assert order.index("skill_b") < order.index("skill_c")

                # Independent skill mixed with dependent skills
                order2 = resolve_dependencies(["skill_d", "skill_c"], manager=manager)
                assert "skill_d" in order2
                assert "skill_a" in order2

                # Circular dependency detection
                manager.add_dependency("skill_a", "skill_c")
                try:
                    resolve_dependencies(["skill_c"], manager=manager)
                    raise AssertionError("expected CircularDependencyError")
                except CircularDependencyError:
                    pass

                # Remove edge and verify resolution works again
                manager.remove_dependency("skill_a", "skill_c")
                order3 = resolve_dependencies(["skill_c"], manager=manager)
                assert order3[0] == "skill_a"

                # Removing a non-existent dependency should raise
                try:
                    manager.remove_dependency("skill_x", "skill_y")
                    raise AssertionError("expected ValueError")
                except ValueError:
                    pass

                # Invalid arguments should raise TypeError
                try:
                    manager.add_dependency(None, "skill_a")  # type: ignore[arg-type]
                    raise AssertionError("expected TypeError")
                except TypeError:
                    pass

                logger.info("skill_dependency_manager selftest passed")
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
