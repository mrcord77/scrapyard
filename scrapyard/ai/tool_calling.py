"""
tool_calling — Register + dispatch model tool calls safely.

### PART-META-JSON
{
  "name": "tool_calling",
  "layer": "ai",
  "purpose": "Register + dispatch model tool calls safely.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: InvalidToolSchema(...); UnknownToolError(...); InvalidToolInput(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `InvalidToolSchema` from `scrapyard.ai.tool_calling` and call it as shown in `example`; run `py -m scrapyard.ai.tool_calling` to see its offline selftest.",
  "example": "from scrapyard.ai.tool_calling import InvalidToolSchema",
  "import_path": "scrapyard.ai.tool_calling"
}
### END-PART-META
"""
from typing import Callable, Dict, List, Any, TypeVar, TYPE_CHECKING
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from scrapyard.ai.tool_calling import ToolRegistry

T = TypeVar('T')
class InvalidToolSchema(Exception):
    pass

class UnknownToolError(Exception):
    pass

class InvalidToolInput(Exception):
    pass

class ToolExecutionError(Exception):
    pass

class BulkDispatchError(Exception):
    pass

class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]

class ToolRegistry:
    """Register Python callables as LLM-invokable tools with JSON-schema-ish specs,
    then dispatch a tool call safely (validates the tool exists, catches errors)."""
    def __init__(self): 
        self.tools = {}
        self.audit_hooks = []
        self.metric_hooks = []
        self.serializer = None
    
    def register(self, name: str, fn: Callable, description: str = "", parameters: dict | None = None, schema: dict | None = None):
        # Original behavior: schema is optional, default to parameters
        if schema is None:
            schema = parameters or {}
        
        try:
            ToolSpec(name=name, description=description, input_schema=schema)
        except ValidationError as e:
            raise InvalidToolSchema(f"Invalid schema: {e}")
        
        self.tools[name] = {"fn": fn, "description": description, "parameters": parameters or {}, "schema": schema}
    
    def specs(self) -> list[dict]:
        return [{"name": n, "description": t["description"], "input_schema": t["parameters"]}
                for n, t in self.tools.items()]
    
    def dispatch(self, name: str, arguments: dict) -> dict:
        if name not in self.tools:
            return {"ok": False, "error": f"unknown tool: {name}"}
        try:
            return {"ok": True, "result": self.tools[name]["fn"](**arguments)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def get_tool_spec(self, name: str) -> dict | None:
        return self.tools.get(name)
    
    def list_tools(self) -> List[dict]:
        return [{"name": n, "description": t["description"], "input_schema": t["parameters"]} for n, t in self.tools.items()]
    
    def bulk_dispatch(self, calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        for call in calls:
            try:
                name = call["name"]
                arguments = call.get("arguments", {})
                if name not in self.tools:
                    raise UnknownToolError(f"Unknown tool: {name}")
                
                spec = ToolSpec(name=name, description=self.tools[name]["description"], input_schema=self.tools[name]["schema"])
                for key, value in arguments.items():
                    if key not in spec.input_schema or not spec.input_schema[key]:
                        raise InvalidToolInput(f"Invalid input for tool {name}: {key} is missing or invalid.")
                
                result = self.tools[name]["fn"](**arguments)
                results.append({"ok": True, "result": result})
            except Exception as e:
                error_message = str(e)
                results.append({"ok": False, "error": error_message})
        
        return results
    
    def set_audit_hook(self, hook: Callable[[str, dict, dict], None]) -> None:
        self.audit_hooks.append(hook)
    
    def set_metric_hook(self, hook: Callable[[str, dict, dict], None]) -> None:
        self.metric_hooks.append(hook)
    
    def set_serializer(self, serializer: Callable[[dict], str]) -> None:
        self.serializer = serializer
    
    def _call_audit_hooks(self, name: str, arguments: Dict[str, Any], result: Dict[str, Any]) -> None:
        for hook in self.audit_hooks:
            try:
                hook(name, arguments, result)
            except Exception as e:
                print(f"Failed to call audit hook: {e}")
    
    def _call_metric_hooks(self, name: str, arguments: Dict[str, Any], result: Dict[str, Any]) -> None:
        for hook in self.metric_hooks:
            try:
                hook(name, arguments, result)
            except Exception as e:
                print(f"Failed to call metric hook: {e}")


def _selftest():
    reg = ToolRegistry()
    reg.register("add", lambda a, b: a + b, description="add numbers",
                 parameters={"a": "int", "b": "int"})
    reg.register("shout", lambda text: text.upper(), description="uppercase",
                 parameters={"text": "str"})

    # specs / list_tools expose registered tools
    specs = reg.specs()
    assert {s["name"] for s in specs} == {"add", "shout"}
    assert reg.get_tool_spec("add")["description"] == "add numbers"
    assert reg.get_tool_spec("missing") is None
    assert len(reg.list_tools()) == 2

    # dispatch invokes the real callable
    ok = reg.dispatch("add", {"a": 2, "b": 3})
    assert ok == {"ok": True, "result": 5}
    # unknown tool and raising tool are safe
    assert reg.dispatch("nope", {})["ok"] is False
    reg.register("boom", lambda: 1 / 0)
    bad = reg.dispatch("boom", {})
    assert bad["ok"] is False and "division" in bad["error"]

    # bulk dispatch mixes successes and failures without aborting
    results = reg.bulk_dispatch([
        {"name": "add", "arguments": {"a": 1, "b": 1}},
        {"name": "unknown", "arguments": {}},
        {"name": "shout", "arguments": {"text": "hi"}},
    ])
    assert results[0] == {"ok": True, "result": 2}
    assert results[1]["ok"] is False
    assert results[2] == {"ok": True, "result": "HI"}

    # hooks are stored and invoked without breaking dispatch
    events = []
    reg.set_audit_hook(lambda n, a, r: events.append(("audit", n)))
    reg.set_metric_hook(lambda n, a, r: events.append(("metric", n)))
    reg._call_audit_hooks("add", {}, {})
    reg._call_metric_hooks("add", {}, {})
    assert ("audit", "add") in events and ("metric", "add") in events

    # serializer setter
    import json
    reg.set_serializer(json.dumps)
    assert reg.serializer({"a": 1}) == '{"a": 1}'
    print("tool_calling selftest passed")


if __name__ == "__main__":
    _selftest()
