"""
sandboxed_skill_executor — Execute registered skills as vetted importable modules under an allowlist, plain-data input validation, and a wall-clock timeout. No eval/exec of code strings, ever.

### PART-META-JSON
{
  "name": "sandboxed_skill_executor",
  "layer": "skills",
  "purpose": "Skill execution with containment: skills are pre-registered import paths under an allowlisted package prefix, loaded via importlib (never exec/eval of strings), fed only JSON-serializable inputs, run with a wall-clock timeout, and their exceptions are wrapped. Not OS-level isolation - see security_notes.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "skill_id registered to a module import path exposing execute(**inputs); inputs dict of plain data.",
  "outputs": "The skill's execute() return value (must itself be plain data).",
  "files_created": [],
  "security_notes": "Containment is at the module level: only pre-registered import paths under allowed prefixes load, code strings are never exec'd, inputs/outputs must be JSON-serializable, and execution has a timeout. It is NOT an OS sandbox - a vetted module still runs with the process's privileges, and a timed-out skill thread is abandoned, not killed. Vet skill modules by review before registering them; run untrusted code in a subprocess/container instead.",
  "ai_usage": "registry.register(skill_id, 'scrapyard.skills.my_skill'); run_skill(skill_id, inputs, registry=registry). Module must define execute(**inputs).",
  "example": "from scrapyard.skills.sandboxed_skill_executor import SkillRegistry, run_skill; r = SkillRegistry(allowed_prefixes=['myskills.']); r.register('hello', 'myskills.hello'); run_skill('hello', {'name': 'x'}, registry=r)",
  "import_path": "scrapyard.skills.sandboxed_skill_executor"
}
### END-PART-META
"""
from __future__ import annotations

import importlib
import json
import logging
import threading
from typing import Any, Dict, Iterable, Optional

STATUS = "core"

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_PREFIXES = ("scrapyard.skills.",)
ENTRYPOINT = "execute"


class SkillExecutionError(Exception):
    """A skill failed: not registered, not allowed, bad inputs, raised, or timed out."""


class SkillRegistry:
    """Explicit allowlist of skill_id -> module import path.

    Only paths under `allowed_prefixes` may be registered — registration is the
    vetting gate; nothing outside the registry can be executed.
    """

    def __init__(self, allowed_prefixes: Iterable[str] = DEFAULT_ALLOWED_PREFIXES):
        self.allowed_prefixes = tuple(allowed_prefixes)
        self._skills: Dict[str, str] = {}

    def register(self, skill_id: str, import_path: str) -> None:
        if not skill_id or not isinstance(skill_id, str):
            raise ValueError("skill_id must be a non-empty string")
        if not any(import_path.startswith(p) for p in self.allowed_prefixes):
            raise SkillExecutionError(
                f"refusing to register {import_path!r}: not under allowed "
                f"prefixes {self.allowed_prefixes}")
        self._skills[skill_id] = import_path

    def resolve(self, skill_id: str) -> str:
        try:
            return self._skills[skill_id]
        except KeyError:
            raise SkillExecutionError(f"skill not registered: {skill_id!r}") from None

    def registered(self) -> Dict[str, str]:
        return dict(self._skills)


def _require_plain_data(value: Any, what: str) -> None:
    """Inputs/outputs must be JSON-serializable plain data — no live objects
    smuggled across the sandbox boundary."""
    try:
        json.dumps(value)
    except (TypeError, ValueError) as e:
        raise SkillExecutionError(f"{what} is not plain JSON-serializable data: {e}") from e


class SandboxEnvironment:
    """Executes one vetted module's entrypoint with a timeout.

    There is deliberately NO string-code path here: the only way in is a
    registered module with an `execute(**inputs)` function.
    """

    def __init__(self, registry: SkillRegistry, timeout_seconds: float = 10.0):
        self.registry = registry
        self.timeout_seconds = timeout_seconds

    def execute(self, skill_id: str, inputs: Dict[str, Any]) -> Any:
        import_path = self.registry.resolve(skill_id)
        if not any(import_path.startswith(p) for p in self.registry.allowed_prefixes):
            raise SkillExecutionError(f"{import_path!r} escaped the allowlist")
        _require_plain_data(inputs, "inputs")

        try:
            module = importlib.import_module(import_path)
        except Exception as e:  # noqa: BLE001 — import failure is a skill failure
            raise SkillExecutionError(f"cannot import skill module {import_path!r}: {e}") from e

        entry = getattr(module, ENTRYPOINT, None)
        if not callable(entry):
            raise SkillExecutionError(
                f"skill module {import_path!r} has no callable {ENTRYPOINT}()")

        result: Dict[str, Any] = {}
        error: Dict[str, BaseException] = {}

        def worker() -> None:
            try:
                result["value"] = entry(**inputs)
            except BaseException as e:  # noqa: BLE001 — wrapped for the caller
                error["exc"] = e

        thread = threading.Thread(target=worker, daemon=True,
                                  name=f"skill:{skill_id}")
        thread.start()
        thread.join(self.timeout_seconds)
        if thread.is_alive():
            raise SkillExecutionError(
                f"skill {skill_id!r} exceeded {self.timeout_seconds}s timeout "
                "(thread abandoned)")
        if "exc" in error:
            raise SkillExecutionError(
                f"skill {skill_id!r} raised {type(error['exc']).__name__}: "
                f"{error['exc']}") from error["exc"]

        value = result.get("value")
        _require_plain_data(value, f"skill {skill_id!r} output")
        return value


def run_skill(skill_id: str, inputs: Dict[str, Any], *,
              registry: SkillRegistry,
              timeout_seconds: float = 10.0) -> Any:
    """Execute a registered skill with validated inputs and a timeout."""
    return SandboxEnvironment(registry, timeout_seconds).execute(skill_id, inputs)


def _selftest():
    import os
    import sys
    import tempfile
    import time
    import uuid

    start = time.time()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        # Build a vetted skill package on disk (files, not code strings).
        pkg = f"sandboxtest_{uuid.uuid4().hex[:8]}"
        pkg_dir = os.path.join(tmp, pkg)
        os.makedirs(pkg_dir)
        with open(os.path.join(pkg_dir, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("")
        with open(os.path.join(pkg_dir, "greet.py"), "w", encoding="utf-8") as f:
            f.write("def execute(name, times=1):\n"
                    "    return {'greeting': ('hello ' + name + '! ') * times}\n")
        with open(os.path.join(pkg_dir, "boom.py"), "w", encoding="utf-8") as f:
            f.write("def execute():\n    raise RuntimeError('kaboom')\n")
        with open(os.path.join(pkg_dir, "slow.py"), "w", encoding="utf-8") as f:
            f.write("import time\n\ndef execute():\n    time.sleep(30)\n")
        with open(os.path.join(pkg_dir, "noentry.py"), "w", encoding="utf-8") as f:
            f.write("VALUE = 1\n")

        sys.path.insert(0, tmp)
        try:
            registry = SkillRegistry(allowed_prefixes=(f"{pkg}.",))
            registry.register("greet", f"{pkg}.greet")
            registry.register("boom", f"{pkg}.boom")
            registry.register("slow", f"{pkg}.slow")
            registry.register("noentry", f"{pkg}.noentry")

            # 1. Vetted module executes for real with typed inputs.
            out = run_skill("greet", {"name": "world", "times": 2}, registry=registry)
            assert out == {"greeting": "hello world! hello world! "}, out

            # 2. Unregistered skill is refused.
            try:
                run_skill("ghost", {}, registry=registry)
            except SkillExecutionError as e:
                assert "not registered" in str(e)
            else:
                raise AssertionError("unregistered skill must be refused")

            # 3. Registration outside the allowlist is refused (no arbitrary imports).
            try:
                registry.register("evil", "os.path")
            except SkillExecutionError as e:
                assert "allowed" in str(e)
            else:
                raise AssertionError("out-of-prefix registration must be refused")

            # 4. Non-plain-data inputs are rejected before any code runs.
            try:
                run_skill("greet", {"name": object()}, registry=registry)
            except SkillExecutionError as e:
                assert "JSON-serializable" in str(e)
            else:
                raise AssertionError("non-serializable inputs must be rejected")

            # 5. Skill exceptions are wrapped, never leaked raw.
            try:
                run_skill("boom", {}, registry=registry)
            except SkillExecutionError as e:
                assert "kaboom" in str(e)
            else:
                raise AssertionError("skill exception must surface as SkillExecutionError")

            # 6. Timeout is enforced.
            try:
                run_skill("slow", {}, registry=registry, timeout_seconds=0.5)
            except SkillExecutionError as e:
                assert "timeout" in str(e)
            else:
                raise AssertionError("timeout must be enforced")

            # 7. Module without execute() is refused.
            try:
                run_skill("noentry", {}, registry=registry)
            except SkillExecutionError as e:
                assert "execute" in str(e)
            else:
                raise AssertionError("module without entrypoint must be refused")

            # 8. The module contains no exec/eval-of-strings path at all.
            import inspect
            src = inspect.getsource(sys.modules[__name__])
            head = src.split("def _selftest", 1)[0]
            assert "exec(" not in head and "eval(" not in head, \
                "executor must not exec/eval strings"
        finally:
            sys.path.remove(tmp)
            for mod in list(sys.modules):
                if mod.startswith(pkg):
                    del sys.modules[mod]

    assert time.time() - start < 20, "selftest exceeded 20s budget"
    logger.info("sandboxed_skill_executor selftest passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
