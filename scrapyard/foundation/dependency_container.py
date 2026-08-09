"""
dependency_container — Tiny service registry / DI container.

### PART-META-JSON
{
  "name": "dependency_container",
  "layer": "foundation",
  "purpose": "Minimal dependency-injection container: named factory registration (singleton or transient), per-service config with runtime overrides, pre-init/post-init/on_destroy lifecycle hooks, bulk registration, env-var config overrides, and in-process state snapshots.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Service names, zero-or-one-arg factories (receive the container), config dicts, hook callables.",
  "outputs": "Resolved service instances; registry snapshots.",
  "files_created": [],
  "security_notes": "Factories are arbitrary callables executed at resolve time — register only trusted code, never factories built from external input. configure_from_env parses environment values as JSON with plain-string fallback (no eval), so env vars can override config values but cannot inject code. Snapshots from serialize_container hold live object references and are for in-process restore only, not for persistence or transport.",
  "ai_usage": "container.register('db', lambda c: make_engine(), singleton=True); later: engine = container.resolve('db').",
  "example": "c = Container(); c.register('svc', lambda c: object()); svc = c.resolve('svc')",
  "import_path": "scrapyard.foundation.dependency_container"
}
### END-PART-META
"""
from __future__ import annotations

import json
import os
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

STATUS = "core"


class ServiceNotFoundError(Exception):
    pass

class InvalidConfigError(Exception):
    pass

class HookExecutionError(Exception):
    pass

class ServiceAlreadyRegisteredError(Exception):
    pass

class SerializationError(Exception):
    pass

class DeserializationError(Exception):
    pass


ENV_VAR_PREFIX = "APP_"
_HOOK_TYPES = ("pre-init", "post-init", "on_destroy")


class Container:
    def __init__(self):
        self._factories: Dict[str, Tuple[Callable, bool]] = {}
        self._singletons: Dict[str, Any] = {}
        self._hooks: Dict[str, Dict[str, List[Callable]]] = {}
        self._config: Dict[str, Dict[str, Any]] = {}

    # --- registration ---

    def register(self, name: str, factory: Callable, singleton: bool = True) -> None:
        if name in self._factories:
            raise ServiceAlreadyRegisteredError(f"Service {name} is already registered.")
        if not callable(factory):
            raise InvalidConfigError(f"Factory for {name} must be callable.")
        self._factories[name] = (factory, singleton)

    def register_with_config(self, name: str, factory: Callable,
                             config: Dict[str, Any], singleton: bool = True) -> None:
        if name in self._factories:
            raise ServiceAlreadyRegisteredError(f"Service {name} is already registered.")
        if not callable(factory):
            raise InvalidConfigError(f"Factory for {name} must be callable.")
        self._config[name] = dict(config)
        self._factories[name] = (factory, singleton)

    def bulk_register(self, config_map: Dict[str, Any]) -> None:
        for name, details in config_map.items():
            if "factory" not in details:
                raise InvalidConfigError(f"Missing factory for service {name}.")
            factory = details["factory"]
            singleton = details.get("singleton", True)
            self.register_with_config(name, factory, details.get("config", {}), singleton)

    # --- resolution ---

    def _fire(self, name: str, hook_type: str) -> None:
        for callback in self._hooks.get(name, {}).get(hook_type, []):
            try:
                callback(self, name)
            except HookExecutionError:
                raise
            except Exception as e:
                raise HookExecutionError(f"{hook_type} hook for {name} failed: {e}") from e

    def resolve(self, name: str) -> Any:
        if name in self._singletons:
            return self._singletons[name]
        if name not in self._factories:
            raise ServiceNotFoundError(f"Service {name} not found.")
        factory, singleton = self._factories[name]
        self._fire(name, "pre-init")
        inst = factory(self)
        if singleton:
            self._singletons[name] = inst
        self._fire(name, "post-init")
        return inst

    def resolve_with_config(self, name: str, config: Optional[Dict[str, Any]] = None) -> Any:
        """Resolve after merging ``config`` overrides into the stored config.
        Overrides invalidate a cached singleton so the factory sees them."""
        if name not in self._factories:
            raise ServiceNotFoundError(f"Service {name} not found.")
        if config:
            self._config.setdefault(name, {}).update(config)
            self._singletons.pop(name, None)
        return self.resolve(name)

    def destroy(self, name: str) -> None:
        """Drop a cached singleton, firing its on_destroy hooks."""
        if name in self._singletons:
            self._fire(name, "on_destroy")
            del self._singletons[name]

    def clear(self) -> None:
        """Destroy all cached singletons (on_destroy hooks fire per service)."""
        for name in list(self._singletons):
            self.destroy(name)

    # --- hooks ---

    def register_hook(self, name: str, hook_type: str, callback: Callable) -> None:
        if hook_type not in _HOOK_TYPES:
            raise ValueError(
                f"Invalid hook type {hook_type}. Valid types are {', '.join(_HOOK_TYPES)}.")
        if not callable(callback):
            raise ValueError("callback must be callable")
        if name not in self._hooks:
            self._hooks[name] = {t: [] for t in _HOOK_TYPES}
        self._hooks[name][hook_type].append(callback)

    # --- introspection / config ---

    def get_all_registered(self) -> List[Dict[str, Any]]:
        return [{
            "name": name,
            "singleton": singleton,
            "config": self._config.get(name, {}),
        } for name, (factory, singleton) in self._factories.items()]

    def configure_from_env(self, prefix: str = ENV_VAR_PREFIX) -> None:
        """Override config values from env vars named ``<prefix><KEY>`` (values
        parsed as JSON, falling back to the raw string)."""
        for name, config in self._config.items():
            for key in list(config.keys()):
                env_key = f"{prefix}{key.upper()}"
                if env_key not in os.environ:
                    continue
                raw = os.environ[env_key]
                try:
                    config[key] = json.loads(raw)
                except json.JSONDecodeError:
                    config[key] = raw
                self._singletons.pop(name, None)  # config changed; rebuild lazily

    def serialize_container(self) -> Dict[str, Any]:
        """In-process snapshot (holds live references; not for persistence)."""
        return {
            "factories": dict(self._factories),
            "singletons": dict(self._singletons),
            "hooks": {k: {t: list(v) for t, v in hooks.items()}
                      for k, hooks in self._hooks.items()},
            "config": {k: dict(v) for k, v in self._config.items()},
        }

    def deserialize_container(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise DeserializationError("Data must be a dictionary.")
        factories = data.get("factories", {})
        for name, entry in factories.items():
            if not (isinstance(entry, tuple) and len(entry) == 2 and callable(entry[0])):
                raise DeserializationError(f"Invalid factory entry for {name}.")
        self._factories = dict(factories)
        self._singletons = dict(data.get("singletons", {}))
        self._hooks = {k: {t: list(v) for t, v in hooks.items()}
                       for k, hooks in data.get("hooks", {}).items()}
        self._config = {k: dict(v) for k, v in data.get("config", {}).items()}

    def set_default_config(self, config: Dict[str, Any]) -> None:
        """Set config defaults for services (existing values win over defaults)."""
        for name, details in config.items():
            if "factory" not in details:
                raise InvalidConfigError(f"Missing factory for service {name}.")
            if "config" not in details:
                continue
            merged = dict(details["config"])
            merged.update(self._config.get(name, {}))
            self._config[name] = merged

    def get_config(self, name: str) -> Dict[str, Any]:
        return self._config.get(name, {})


def hook(hook_type: str):
    """Decorator marking a callable as a lifecycle hook; exceptions inside it
    are wrapped in HookExecutionError."""
    if hook_type not in _HOOK_TYPES:
        raise ValueError(f"Invalid hook type {hook_type}.")

    def decorator(callback: Callable):
        @wraps(callback)
        def wrapper(*args, **kwargs):
            try:
                return callback(*args, **kwargs)
            except Exception as e:
                raise HookExecutionError(
                    f"Hook {callback.__name__} failed with error: {e}") from e
        wrapper._hook_type = hook_type
        return wrapper
    return decorator


def _selftest() -> None:
    c = Container()

    # basic register/resolve, singleton vs transient
    c.register("db", lambda cc: object(), singleton=True)
    c.register("req", lambda cc: object(), singleton=False)
    assert c.resolve("db") is c.resolve("db")
    assert c.resolve("req") is not c.resolve("req")
    try:
        c.register("db", lambda cc: 1)
        raise AssertionError("duplicate registration accepted")
    except ServiceAlreadyRegisteredError:
        pass
    try:
        c.resolve("missing")
        raise AssertionError("missing service resolved")
    except ServiceNotFoundError:
        pass

    # config-driven service + runtime overrides
    c.register_with_config("greeter",
                           lambda cc: f"hello value={cc.get_config('greeter')['value']}",
                           {"value": 42})
    assert c.resolve("greeter") == "hello value=42"
    assert c.resolve_with_config("greeter", {"value": 50}) == "hello value=50"
    assert c.get_config("greeter")["value"] == 50

    # lifecycle hooks actually fire, in order
    events: list = []
    c.register("svc", lambda cc: events.append("factory") or "SVC", singleton=True)
    c.register_hook("svc", "pre-init", lambda cc, name: events.append(f"pre:{name}"))
    c.register_hook("svc", "post-init", lambda cc, name: events.append(f"post:{name}"))
    c.register_hook("svc", "on_destroy", lambda cc, name: events.append(f"destroy:{name}"))
    c.resolve("svc")
    c.destroy("svc")
    assert events == ["pre:svc", "factory", "post:svc", "destroy:svc"]
    try:
        c.register_hook("svc", "mid-init", lambda cc, name: None)
        raise AssertionError("bad hook type accepted")
    except ValueError:
        pass
    # a failing hook surfaces as HookExecutionError
    c.register("fragile", lambda cc: 1)
    c.register_hook("fragile", "pre-init", lambda cc, name: 1 / 0)
    try:
        c.resolve("fragile")
        raise AssertionError("hook failure swallowed")
    except HookExecutionError:
        pass

    # hook decorator wraps exceptions
    @hook("post-init")
    def bad_hook(cc, name):
        raise RuntimeError("boom")
    assert bad_hook._hook_type == "post-init"
    try:
        bad_hook(None, "x")
        raise AssertionError("decorated hook did not wrap")
    except HookExecutionError:
        pass

    # bulk register + introspection
    c2 = Container()
    c2.bulk_register({
        "a": {"factory": lambda cc: "A", "config": {"k": 1}},
        "b": {"factory": lambda cc: "B", "singleton": False},
    })
    names = {e["name"] for e in c2.get_all_registered()}
    assert names == {"a", "b"} and c2.resolve("a") == "A"
    try:
        c2.bulk_register({"bad": {"config": {}}})
        raise AssertionError("factory-less bulk entry accepted")
    except InvalidConfigError:
        pass

    # env overrides (JSON parsed, string fallback; singleton invalidated)
    c3 = Container()
    c3.register_with_config("sized", lambda cc: cc.get_config("sized")["size"], {"size": 1, "label": "x"})
    assert c3.resolve("sized") == 1
    os.environ["APP_SIZE"] = "99"
    os.environ["APP_LABEL"] = "not-json"
    try:
        c3.configure_from_env()
        assert c3.get_config("sized") == {"size": 99, "label": "not-json"}
        assert c3.resolve("sized") == 99
    finally:
        os.environ.pop("APP_SIZE", None)
        os.environ.pop("APP_LABEL", None)

    # snapshot round-trip (in-process)
    snap = c3.serialize_container()
    c4 = Container()
    c4.deserialize_container(snap)
    assert c4.resolve("sized") == 99
    try:
        c4.deserialize_container("nope")  # type: ignore[arg-type]
        raise AssertionError("bad snapshot accepted")
    except DeserializationError:
        pass

    # defaults do not clobber existing config
    c4.set_default_config({"sized": {"factory": lambda cc: None,
                                     "config": {"size": 5, "extra": True}}})
    assert c4.get_config("sized")["size"] == 99 and c4.get_config("sized")["extra"] is True

    print("dependency_container selftest: PASS")


if __name__ == "__main__":
    _selftest()


# --- grafted from original part (API stability) ---
container = Container()
