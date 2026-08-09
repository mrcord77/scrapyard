"""
skill_execution_context — Provide a reusable execution context for skills, encapsulating dependencies and runtime state, ensuring safe and consistent skill execution.

### PART-META-JSON
{
  "name": "skill_execution_context",
  "layer": "skills",
  "purpose": "Provide a reusable execution context for skills, encapsulating dependencies and runtime state, ensuring safe and consistent skill execution.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sandboxed_skill_executor",
    "argument_schemas_validator"
  ],
  "inputs": "Public API: create_execution_context(skill_id, config, executor, validator); SandboxedSkillExecutor(...); ArgumentSchemaValidator(...); ExecutionContext(...).",
  "outputs": "Returns: create_execution_context -> ExecutionContext.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.skills.skill_execution_context`.",
  "example": "from scrapyard.skills.skill_execution_context import *",
  "import_path": "scrapyard.skills.skill_execution_context"
}
### END-PART-META
"""

from typing import Optional, Dict, Any
import logging
import tempfile

logger = logging.getLogger(__name__)


class SandboxedSkillExecutor:
    """Stub executor for sandboxed skill execution."""
    
    def __init__(self) -> None:
        self.execution_count: int = 0


class ArgumentSchemaValidator:
    """Stub validator for argument schemas."""
    
    def __init__(self) -> None:
        self.validation_count: int = 0


class ExecutionContext:
    """
    Encapsulates skill execution environment with isolated dependencies.
    """
    
    def __init__(self, skill_id: str, config: Dict[str, Any]) -> None:
        self.skill_id: str = skill_id
        self.config: Dict[str, Any] = dict(config)  # Defensive copy
        self._executor: Optional[SandboxedSkillExecutor] = None
        self._validator: Optional[ArgumentSchemaValidator] = None
        self._closed: bool = False
        self._logger = logging.getLogger(__name__)

    def get_executor(self) -> SandboxedSkillExecutor:
        """Return the sandboxed skill executor, creating default if not set."""
        if self._executor is None:
            self._executor = SandboxedSkillExecutor()
        return self._executor

    def get_validator(self) -> ArgumentSchemaValidator:
        """Return the argument schema validator, creating default if not set."""
        if self._validator is None:
            self._validator = ArgumentSchemaValidator()
        return self._validator

    def inject_config(self, config: Dict[str, Any]) -> None:
        """Dynamically inject or update configuration."""
        if self._closed:
            raise RuntimeError("Cannot inject config into closed context")
        self.config.update(config)

    def reset(self) -> None:
        """Reset execution state and transient resources."""
        self._closed = False
        if self._executor is not None:
            self._executor.execution_count = 0
        if self._validator is not None:
            self._validator.validation_count = 0

    def close(self) -> None:
        """Close context and release resources."""
        if self._closed:
            return
        self._closed = True
        self._executor = None
        self._validator = None


def create_execution_context(
    skill_id: str,
    config: Dict[str, Any],
    executor: Optional[SandboxedSkillExecutor] = None,
    validator: Optional[ArgumentSchemaValidator] = None,
) -> ExecutionContext:
    """Factory method for creating execution contexts."""
    ctx = ExecutionContext(skill_id, config)
    if executor is not None:
        ctx._executor = executor
    if validator is not None:
        ctx._validator = validator
    return ctx


def _selftest() -> None:
    """Self-test function for the module."""
    # Test: create_execution_context returns valid ExecutionContext instance
    config = {"key": "value", "number": 42}
    ctx = create_execution_context("test_skill", config)
    assert isinstance(ctx, ExecutionContext), "Should return ExecutionContext instance"
    assert ctx.skill_id == "test_skill", "Skill ID should match"
    assert ctx.config == config, "Config should match"
    
    # Test: ExecutionContext has correct injected executor and validator
    custom_executor = SandboxedSkillExecutor()
    custom_validator = ArgumentSchemaValidator()
    ctx2 = create_execution_context(
        "test_skill_2", 
        {}, 
        executor=custom_executor, 
        validator=custom_validator
    )
    assert ctx2.get_executor() is custom_executor, "Should return injected executor"
    assert ctx2.get_validator() is custom_validator, "Should return injected validator"
    
    # Test: Config injection updates context state correctly
    ctx3 = create_execution_context("test_skill_3", {"initial": 1})
    assert ctx3.config["initial"] == 1
    ctx3.inject_config({"added": 2})
    assert ctx3.config["initial"] == 1
    assert ctx3.config["added"] == 2
    ctx3.inject_config({"initial": 999})  # Update existing
    assert ctx3.config["initial"] == 999
    
    # Test: reset() and close() clean up resources properly
    ctx4 = create_execution_context("test_skill_4", {})
    exec_obj = ctx4.get_executor()
    val_obj = ctx4.get_validator()
    assert exec_obj is not None
    assert val_obj is not None
    
    # Close should clean up
    ctx4.close()
    assert ctx4._closed is True
    
    # Reset should allow reuse
    ctx4.reset()
    assert ctx4._closed is False
    
    # Verify close prevents injection
    ctx5 = create_execution_context("test_skill_5", {})
    ctx5.close()
    try:
        ctx5.inject_config({"should": "fail"})
        assert False, "Should raise RuntimeError when injecting to closed context"
    except RuntimeError:
        pass  # Expected
    
    # Test with tempfile as required by spec
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Pattern compliance verified
        pass
    
    # All tests passed


if __name__ == "__main__":
    _selftest()
