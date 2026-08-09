"""
planner — Reusable goal-decomposition planner: forward-search over a registered action library with preconditions and effects, producing ordered plan steps that reach a desired goal state from the current state.

### PART-META-JSON
{
  "name": "planner",
  "layer": "agents",
  "purpose": "Domain-agnostic planner: actions are registered in an ActionLibrary with preconditions and effects, and generate_plan() forward-searches (breadth-first, deterministic) for an ordered step sequence that transforms the current state into the goal state, reporting unmet dependencies by name when the goal is unreachable. Includes SQLAlchemy persistence for planner state/goal.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "executor",
    "sqlalchemy"
  ],
  "inputs": "ActionLibrary().register(ActionSpec(name, preconditions={var: value|REQUIRED}, effects={var: value}, params={})); generate_plan(state_dict, goal_dict, library). Goal values are desired state entries.",
  "outputs": "List of step dicts {action, params, dependencies}; ValueError naming the unmet dependency when no action sequence can reach the goal; Planner ORM rows persisting name/state/goal.",
  "files_created": [],
  "security_notes": "Pure computation over caller-registered ActionSpecs: no callables are executed during planning and no eval/exec is used, so a hostile goal/state dict can at worst make the bounded BFS return 'unreachable'. Search depth is capped (max_depth) to prevent unbounded exploration. DB persistence stores only JSON state/goal supplied by the caller.",
  "ai_usage": "lib = ActionLibrary(); lib.register(ActionSpec('inspect', {}, {'inspected': True})); steps = generate_plan({'inspected': False}, {'inspected': True}, lib).",
  "example": "from scrapyard.agents.planner import ActionLibrary, ActionSpec, generate_plan",
  "import_path": "scrapyard.agents.planner"
}
### END-PART-META
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from scrapyard.database.base_model import IntPKModel
from sqlalchemy.orm import Mapped, mapped_column, Session
from sqlalchemy import String, JSON, Integer, create_engine
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class _Required:
    """Sentinel: precondition variable must be present and truthy in state,
    whatever its concrete value (e.g. a permit id)."""

    def __repr__(self):  # pragma: no cover - repr cosmetics
        return "REQUIRED"


REQUIRED = _Required()


@dataclass
class PlanStep:
    """Represents a single step in an execution plan."""
    action: str
    params: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionSpec:
    """A plannable action: name, preconditions it needs, effects it produces."""
    name: str
    preconditions: tuple = ()
    effects: tuple = ()
    params: tuple = ()

    def __init__(self, name: str, preconditions: Dict[str, Any] = None,
                 effects: Dict[str, Any] = None, params: Dict[str, Any] = None):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "preconditions",
                           tuple(sorted((preconditions or {}).items(),
                                        key=lambda kv: kv[0])))
        object.__setattr__(self, "effects",
                           tuple(sorted((effects or {}).items(),
                                        key=lambda kv: kv[0])))
        object.__setattr__(self, "params",
                           tuple(sorted((params or {}).items(),
                                        key=lambda kv: kv[0])))

    @property
    def precondition_dict(self) -> Dict[str, Any]:
        return dict(self.preconditions)

    @property
    def effect_dict(self) -> Dict[str, Any]:
        return dict(self.effects)

    @property
    def param_dict(self) -> Dict[str, Any]:
        return dict(self.params)


class ActionLibrary:
    """Registry of ActionSpecs the planner searches over."""

    def __init__(self):
        self._actions: Dict[str, ActionSpec] = {}

    def register(self, spec: ActionSpec) -> None:
        if not isinstance(spec, ActionSpec):
            raise TypeError("register() expects an ActionSpec")
        self._actions[spec.name] = spec

    def get(self, name: str) -> Optional[ActionSpec]:
        return self._actions.get(name)

    def all(self) -> List[ActionSpec]:
        # deterministic ordering for reproducible plans
        return [self._actions[k] for k in sorted(self._actions)]

    def __len__(self):
        return len(self._actions)


def _satisfied(state: Dict[str, Any], conditions: Dict[str, Any]) -> bool:
    for var, want in conditions.items():
        have = state.get(var)
        if isinstance(want, _Required):
            if not have:
                return False
        elif have != want:
            return False
    return True


def _missing(state: Dict[str, Any], conditions: Dict[str, Any]) -> List[str]:
    out = []
    for var, want in conditions.items():
        have = state.get(var)
        if isinstance(want, _Required):
            if not have:
                out.append(var)
        elif have != want:
            out.append(var)
    return out


def _freeze(state: Dict[str, Any]) -> tuple:
    return tuple(sorted((k, repr(v)) for k, v in state.items()))


def generate_plan(state: dict, goal: dict,
                  library: Optional[ActionLibrary] = None,
                  max_depth: int = 12) -> List[Dict[str, Any]]:
    """Find an ordered action sequence that transforms `state` into a state
    satisfying `goal`, using breadth-first search over `library`.

    :param state: current world state as {var: value}.
    :param goal: desired state entries as {var: value} (subset match).
    :param library: registered ActionLibrary; required when goal is not
        already satisfied.
    :param max_depth: search depth cap.
    :return: list of {action, params, dependencies} dicts (may be empty when
        the goal already holds).
    :raises ValueError: on invalid inputs, or - naming the unmet dependency -
        when the goal is unreachable with the registered actions.
    """
    if not isinstance(state, dict) or not isinstance(goal, dict):
        raise ValueError("State and goal must be dictionaries.")

    if _satisfied(state, goal):
        return []

    if library is None or len(library) == 0:
        raise ValueError("An ActionLibrary with registered actions is required "
                         "to plan for an unmet goal.")

    # Which goal/precondition variables can any action ever produce?
    producible = set()
    for spec in library.all():
        producible.update(spec.effect_dict.keys())

    # BFS over states (deterministic: library.all() is sorted)
    start = dict(state)
    frontier = [(start, [])]
    seen = {_freeze(start)}
    for _ in range(max_depth):
        next_frontier = []
        for cur, path in frontier:
            for spec in library.all():
                if not _satisfied(cur, spec.precondition_dict):
                    continue
                new_state = dict(cur)
                new_state.update(spec.effect_dict)
                key = _freeze(new_state)
                if key in seen:
                    continue
                seen.add(key)
                new_path = path + [spec]
                if _satisfied(new_state, goal):
                    return [PlanStep(
                        action=s.name,
                        params=s.param_dict,
                        dependencies=sorted(s.precondition_dict.keys()),
                    ).__dict__ for s in new_path]
                next_frontier.append((new_state, new_path))
        frontier = next_frontier
        if not frontier:
            break

    # Unreachable: name the unmet dependencies to make the failure actionable.
    blockers = []
    for var in _missing(state, goal):
        if var not in producible:
            blockers.append(var)
    for spec in library.all():
        for var in _missing(state, spec.precondition_dict):
            if var not in producible and var not in blockers:
                blockers.append(var)
    if blockers:
        raise ValueError(
            f"Dependency {', '.join(sorted(blockers))} not met.")
    raise ValueError("Goal unreachable with the registered actions "
                     f"within depth {max_depth}.")


class Planner(IntPKModel):
    """
    Database model for persisting planner configurations and states.

    Allows storage of agent goals and current state for long-term planning
    across sessions.
    """
    __tablename__ = "planners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    goal: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert planner instance to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "goal": self.goal,
        }

    def generate(self, library: Optional[ActionLibrary] = None,
                 max_depth: int = 12) -> List[Dict[str, Any]]:
        """Generate a plan from this planner's stored state and goal against
        the given action library."""
        return generate_plan(self.state, self.goal, library, max_depth=max_depth)


def decompose_plan(plan) -> List[Any]:
    """Decompose a Plan-like object (anything with .steps, or a list of step
    dicts) into simple step objects with a .name attribute — the shape the
    executor consumes."""
    steps = getattr(plan, "steps", plan)
    out = []
    for s in steps:
        if isinstance(s, dict):
            name = s.get("action") or s.get("name") or ""
        else:
            name = getattr(s, "action", None) or getattr(s, "name", str(s))
        out.append(type("Step", (), {"name": name})())
    return out


class Plan:
    """Lightweight named container of plan steps (used by the executor)."""

    def __init__(self, name: str, steps: List[Any]):
        self.name = name
        self.steps = steps


def _example_disposal_library() -> ActionLibrary:
    """EXAMPLE domain (scrapyard part disposal) used by the selftest. The
    planner core knows nothing about it."""
    lib = ActionLibrary()
    lib.register(ActionSpec(
        "inspect_parts",
        preconditions={},
        effects={"inspected_parts": True},
        params={"part_types": ["metal", "plastic"]},
    ))
    lib.register(ActionSpec(
        "sort_parts",
        preconditions={"inspected_parts": True},
        effects={"parts_sorted": True},
        params={"destination": "recycling_bin"},
    ))
    lib.register(ActionSpec(
        "dispose_parts",
        preconditions={"inspected_parts": True, "disposal_permit": REQUIRED},
        effects={"parts_disposed": True},
        params={"destination": "disposal_bin"},
    ))
    return lib


def _selftest():
    """Verify goal decomposition, dependency reporting, and persistence."""
    lib = _example_disposal_library()

    # Not yet inspected -> plan must inspect first, then sort.
    plan = generate_plan({"inspected_parts": False}, {"parts_sorted": True}, lib)
    assert [s["action"] for s in plan] == ["inspect_parts", "sort_parts"], plan
    assert "inspected_parts" in plan[1]["dependencies"]

    # Already inspected -> single step.
    plan2 = generate_plan({"inspected_parts": True}, {"parts_sorted": True}, lib)
    assert [s["action"] for s in plan2] == ["sort_parts"]

    # Goal already satisfied -> empty plan.
    assert generate_plan({"parts_sorted": True}, {"parts_sorted": True}, lib) == []

    # Invalid inputs.
    for bad_state, bad_goal in ((None, {"a": 1}), ({"a": 1}, None)):
        try:
            generate_plan(bad_state, bad_goal, lib)
            raise AssertionError("Expected ValueError for non-dict input.")
        except (ValueError, TypeError):
            pass

    # Disposal without permit: no action produces disposal_permit -> named error.
    try:
        generate_plan({"inspected_parts": True}, {"parts_disposed": True}, lib)
        raise AssertionError("Expected ValueError due to unmet dependency.")
    except ValueError as e:
        assert "Dependency" in str(e), f"Unexpected error message: {e}"
        assert "disposal_permit" in str(e), f"Expected disposal_permit in error: {e}"

    # Disposal with permit succeeds (REQUIRED matches any truthy value).
    plan3 = generate_plan(
        {"inspected_parts": True, "disposal_permit": "XYZ-123"},
        {"parts_disposed": True}, lib)
    assert [s["action"] for s in plan3] == ["dispose_parts"]

    # Multi-goal: inspect once, then both sort and dispose (order = BFS-found).
    plan4 = generate_plan(
        {"disposal_permit": "XYZ-123"},
        {"parts_sorted": True, "parts_disposed": True}, lib)
    names = [s["action"] for s in plan4]
    assert names[0] == "inspect_parts" and set(names[1:]) == {"sort_parts", "dispose_parts"}

    # decompose_plan bridges plans to the executor's step shape.
    steps = decompose_plan(Plan("p", plan))
    assert [s.name for s in steps] == ["inspect_parts", "sort_parts"]

    # Persistence round-trip.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "planner_test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
        IntPKModel.metadata.create_all(engine)
        with Session(engine) as session:
            planner = Planner(
                name="test_planner",
                state={"inspected_parts": False, "location": "yard_a"},
                goal={"parts_sorted": True},
            )
            session.add(planner)
            session.commit()
            retrieved = session.query(Planner).filter_by(name="test_planner").first()
            assert retrieved is not None
            assert retrieved.state["location"] == "yard_a"
            assert retrieved.goal["parts_sorted"] is True
            instance_plan = retrieved.generate(lib)
            assert [s["action"] for s in instance_plan] == ["inspect_parts", "sort_parts"]
        engine.dispose()

    logger.info("planner selftest passed")


if __name__ == "__main__":
    _selftest()
