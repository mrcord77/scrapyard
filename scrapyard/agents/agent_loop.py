"""
agent_loop — Generic perceive/plan/act loop for agents: perception reads injected sensors and the task payload, planning maps goal entries onto registered tool capabilities, and dispatch invokes the registered tool callables and returns their real results.

### PART-META-JSON
{
  "name": "agent_loop",
  "layer": "agents",
  "purpose": "Generic perceive/plan/act agent loop: perceive() merges injected sensor readings with the task payload, plan() maps goal entries onto registered tool capabilities via a rule-based policy, and dispatch_tool()/act() invoke the registered tool callables with their arguments and collect real results. Persists tool definitions through the shared ToolModel from agents/tool_registry.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "tool_registry",
    "sqlalchemy"
  ],
  "inputs": "AgentLoop(sensors={name: callable_or_value}, tools={name: callable}); register_tool(name, fn); run(goal) or perceive()/plan(state, goal)/act(plan). Goals: {'tasks': [{'tool': name, 'args': {...}}]} or {tool_name: args_dict}.",
  "outputs": "perceive() -> {'observations', 'task'}; plan() -> List[Action] with tool_name/args; act()/run() -> actions executed with .result set from the actual tool return value and .status completed/failed.",
  "files_created": [],
  "security_notes": "Tools are plain Python callables invoked with caller-supplied kwargs: register only trusted callables and validate goal/task payloads before passing them in (no eval/exec is used anywhere). Tool exceptions are caught per-action and recorded as status='failed' rather than crashing the loop. Persistence uses the shared tool_registry ToolModel table (tool_registry_tools); no secrets are stored or logged.",
  "ai_usage": "loop = AgentLoop(sensors={'clock': time.time}); loop.register_tool('add', lambda a, b: a + b); loop.run({'tasks': [{'tool': 'add', 'args': {'a': 1, 'b': 2}}]}).",
  "example": "from scrapyard.agents.agent_loop import AgentLoop",
  "import_path": "scrapyard.agents.agent_loop"
}
### END-PART-META
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Callable, Optional
import os
import logging
import tempfile

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# Shared persistence model: the single source of truth for stored tool
# definitions lives in agents/tool_registry (table: tool_registry_tools).
from scrapyard.agents.tool_registry import ToolModel, ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    fn: Optional[Callable[..., Any]] = None


@dataclass
class Task:
    task_id: int
    tool_name: str
    action: Any  # arguments payload (dict) for the tool


@dataclass
class Action:
    action_id: int
    status: str = "pending"
    tool_name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    result: Any = None


@dataclass
class State:
    agent_id: int
    state_data: Dict[str, Any]


@dataclass
class Goal:
    goal_id: int
    goal_data: Dict[str, Any]


@dataclass
class Plan:
    actions: List[Action]
    plan_id: int = field(default=None)


def _goal_to_action_specs(goal: Dict[str, Any], known_tools) -> List[Dict[str, Any]]:
    """Rule-based goal -> action policy over registered capabilities.

    Accepted goal shapes:
      {"tasks": [{"tool": name, "args": {...}}, ...]}   explicit task list
      {tool_name: {...args...}, ...}                    map of tool -> args
    Only entries matching a registered tool produce actions; unknown entries
    are reported via a ValueError so the caller learns the capability gap.
    """
    specs: List[Dict[str, Any]] = []
    unknown: List[str] = []
    if not isinstance(goal, dict):
        raise ValueError("goal must be a dict")
    entries: List[tuple]
    if isinstance(goal.get("tasks"), list):
        entries = [(t.get("tool"), t.get("args") or {}) for t in goal["tasks"]
                   if isinstance(t, dict)]
    else:
        entries = [(k, v if isinstance(v, dict) else {"value": v})
                   for k, v in goal.items() if k not in ("goal_data",)]
        # legacy shape {"goal_data": {...}}: treat inner dict as the goal
        if not entries and isinstance(goal.get("goal_data"), dict):
            return _goal_to_action_specs(goal["goal_data"], known_tools)
    for name, args in entries:
        if name in known_tools:
            specs.append({"tool": name, "args": dict(args)})
        else:
            unknown.append(str(name))
    if unknown and not specs:
        raise ValueError(f"no registered capability for goal entries: {unknown}")
    return specs


class AgentLoop:
    """Perceive -> plan -> act loop over injected sensors and registered tools."""

    def __init__(self, sensors: Optional[Dict[str, Any]] = None,
                 tools: Optional[Dict[str, Callable[..., Any]]] = None):
        self._sensors: Dict[str, Any] = dict(sensors or {})
        self._tools: Dict[str, Tool] = {}
        self._next_action_id = 1
        self._next_task_id = 1
        for name, fn in (tools or {}).items():
            self.register_tool(name, fn)
        # Optional DB-backed registry (shared model with agents/tool_registry)
        self.tool_registry: Optional[ToolRegistry] = None

    # -- capability registration -------------------------------------------
    def register_tool(self, name: str, fn: Callable[..., Any],
                      description: str = "") -> None:
        if not callable(fn):
            raise TypeError(f"tool '{name}' must be callable")
        self._tools[name] = Tool(name=name, description=description, fn=fn)

    def register_sensor(self, name: str, source: Any) -> None:
        """A sensor is a zero-arg callable or a plain value to be read as-is."""
        self._sensors[name] = source

    def attach_registry(self, registry: ToolRegistry) -> None:
        """Attach a DB-backed ToolRegistry (from agents/tool_registry) so tool
        definitions persist in the shared tool_registry_tools table."""
        self.tool_registry = registry

    # -- loop phases --------------------------------------------------------
    def perceive(self, task: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Read every injected sensor (call callables, copy values) and merge
        with the current task payload."""
        observations: Dict[str, Any] = {}
        for name, source in self._sensors.items():
            try:
                observations[name] = source() if callable(source) else source
            except Exception as e:  # a failing sensor must not kill the loop
                observations[name] = {"error": str(e)}
        return {"observations": observations, "task": dict(task or {})}

    def plan(self, state: Dict[str, Any], goal: Dict[str, Any]) -> List[Action]:
        """Map goal entries onto registered capabilities (rule-based policy)."""
        specs = _goal_to_action_specs(goal, self._tools)
        actions: List[Action] = []
        for spec in specs:
            actions.append(Action(action_id=self._next_action_id,
                                  tool_name=spec["tool"], args=spec["args"]))
            self._next_action_id += 1
        return actions

    def dispatch_tool(self, task: Task) -> Any:
        """Invoke the registered tool callable with the task's argument payload
        and return the tool's actual result."""
        tool = self._tools.get(task.tool_name)
        if tool is None or tool.fn is None:
            raise KeyError(f"unknown tool: {task.tool_name}")
        args = task.action if isinstance(task.action, dict) else {}
        return tool.fn(**args)

    def act(self, plan: List[Action]) -> List[Action]:
        for action in plan:
            task = Task(task_id=self._next_task_id,
                        tool_name=action.tool_name, action=action.args)
            self._next_task_id += 1
            try:
                action.result = self.dispatch_tool(task)
                action.status = "completed"
                logger.debug("action %s (%s) -> %r", action.action_id,
                             action.tool_name, action.result)
            except Exception as e:
                action.result = {"error": str(e)}
                action.status = "failed"
                logger.warning("action %s (%s) failed: %s", action.action_id,
                               action.tool_name, e)
        return plan

    def run(self, goal: Dict[str, Any],
            task: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """One full loop iteration: perceive -> plan -> act."""
        state = self.perceive(task)
        plan = self.plan(state, goal)
        self.act(plan)
        return {"state": state, "actions": plan,
                "ok": all(a.status == "completed" for a in plan)}


class Planner:
    """Standalone rule-based planner over an AgentLoop's registered tools."""

    def __init__(self, capabilities: Optional[Dict[str, Callable[..., Any]]] = None):
        self._capabilities = dict(capabilities or {})

    def generate_plan(self, state: Dict[str, Any],
                      goal: Dict[str, Any]) -> List[Action]:
        specs = _goal_to_action_specs(goal, self._capabilities)
        return [Action(action_id=i + 1, tool_name=s["tool"], args=s["args"])
                for i, s in enumerate(specs)]


class Executor:
    """Executes Action lists using a tool dispatcher (an AgentLoop or any
    object exposing dispatch_tool(Task))."""

    def __init__(self, dispatcher: Optional[AgentLoop] = None):
        self.dispatcher = dispatcher

    def step(self, action: Action) -> Action:
        if self.dispatcher is not None and action.tool_name:
            try:
                action.result = self.dispatcher.dispatch_tool(
                    Task(task_id=action.action_id, tool_name=action.tool_name,
                         action=action.args))
                action.status = "completed"
            except Exception as e:
                action.result = {"error": str(e)}
                action.status = "failed"
        else:
            action.status = "completed"
        return action

    def execute_steps(self, plan: List[Action]) -> List[Action]:
        return [self.step(a) for a in plan]


def _selftest():
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    db_path = os.path.join(temp_dir.name, "test.db")
    engine = create_engine(f"sqlite:///{db_path}")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    ToolModel.metadata.create_all(bind=engine)

    # Real tools with real results
    calls = []

    def add(a, b):
        calls.append(("add", a, b))
        return a + b

    def concat(x, y):
        return f"{x}{y}"

    loop = AgentLoop(sensors={"battery": lambda: 0.87, "site": "yard_a"})
    loop.register_tool("add", add, "add two numbers")
    loop.register_tool("concat", concat, "concatenate strings")

    # perceive reads real sensors + task payload
    perception = loop.perceive({"job": "sum-things"})
    assert perception["observations"]["battery"] == 0.87
    assert perception["observations"]["site"] == "yard_a"
    assert perception["task"]["job"] == "sum-things"

    # plan maps goal onto registered capabilities
    goal = {"tasks": [{"tool": "add", "args": {"a": 2, "b": 3}},
                      {"tool": "concat", "args": {"x": "scrap", "y": "yard"}}]}
    plan = loop.plan(perception, goal)
    assert [a.tool_name for a in plan] == ["add", "concat"]

    # act dispatches the real callables and captures real results
    loop.act(plan)
    assert plan[0].status == "completed" and plan[0].result == 5
    assert plan[1].status == "completed" and plan[1].result == "scrapyard"
    assert calls == [("add", 2, 3)]

    # dispatch_tool surfaces unknown tools
    try:
        loop.dispatch_tool(Task(task_id=99, tool_name="nope", action={}))
        raise AssertionError("expected KeyError for unknown tool")
    except KeyError:
        pass

    # failing tool -> failed action, loop survives
    loop.register_tool("boom", lambda: 1 / 0)
    res = loop.run({"tasks": [{"tool": "boom", "args": {}}]})
    assert res["actions"][0].status == "failed" and not res["ok"]

    # map-shaped goal
    res2 = loop.run({"add": {"a": 10, "b": 5}})
    assert res2["actions"][0].result == 15 and res2["ok"]

    # unknown-only goal raises (capability gap is surfaced, not swallowed)
    try:
        loop.plan({}, {"fly_to_moon": {}})
        raise AssertionError("expected ValueError for unknown capability")
    except ValueError:
        pass

    # standalone Planner + Executor
    planner = Planner(capabilities={"add": add})
    p2 = planner.generate_plan({}, {"add": {"a": 1, "b": 1}})
    assert len(p2) == 1 and p2[0].tool_name == "add"
    executor = Executor(dispatcher=loop)
    executor.execute_steps(p2)
    assert p2[0].status == "completed" and p2[0].result == 2

    # shared persistence through tool_registry's ToolModel (renamed table)
    registry = ToolRegistry(f"sqlite:///{db_path}")
    registry._initialize_db()
    registry.register_tool(ToolModel(name="add", description="add two numbers"))
    stored = registry.dispatch_tool("add")
    assert stored is not None and stored.name == "add"
    assert ToolModel.__tablename__ == "tool_registry_tools"
    loop.attach_registry(registry)
    assert loop.tool_registry is registry
    registry._close_db()

    session = SessionLocal()
    session.close()
    engine.dispose()
    temp_dir.cleanup()
    logger.info("agent_loop selftest passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
