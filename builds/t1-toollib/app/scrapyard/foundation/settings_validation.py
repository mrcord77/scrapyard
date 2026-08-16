"""
settings_validation — Fail-fast validation of required settings at boot.

### PART-META-JSON
{
  "name": "settings_validation",
  "layer": "foundation",
  "purpose": "Boot-time settings validation: assert required attributes on settings objects and required env vars (raising SettingsError with the full missing list), policy-driven env checks, bulk validation across settings objects, validation hooks, serialization after validation, and logged error reporting.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "pydantic"
  ],
  "inputs": "Settings objects (any attribute-bearing object), required-name lists, env var names, an optional ValidationPolicy.",
  "outputs": "None on success; SettingsError naming every missing item on failure; env-value dicts.",
  "files_created": [],
  "security_notes": "Error messages name missing KEYS only, never values, so a failed boot log cannot leak secrets. require_env/validate_env_with_policy return the actual env values — treat those dicts as sensitive and do not log them. Empty-string env vars count as missing (fail-fast beats an empty credential reaching a client library).",
  "ai_usage": "At app boot: validate_settings(settings, ['database_url', 'secret_key']); require_env('DATABASE_URL') for raw env deployments.",
  "example": "validate_settings(settings, ['database_url', 'secret_key'])",
  "import_path": "scrapyard.foundation.settings_validation"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional, TypeVar

from pydantic import BaseModel

STATUS = "core"

T = TypeVar('T')

logger = logging.getLogger("scrapyard.foundation.settings_validation")


class ValidationPolicy(BaseModel):
    type_check: bool = True
    format_check: bool = True
    min_max_check: bool = True
    enum_check: bool = True


class SettingsError(RuntimeError):
    pass


_global_policy = ValidationPolicy()


def configure_validation_policy(policy: ValidationPolicy) -> None:
    """Set the module-wide default policy used when a call passes policy=None."""
    global _global_policy
    if not isinstance(policy, ValidationPolicy):
        raise TypeError("policy must be a ValidationPolicy")
    _global_policy = policy


def get_validation_policy() -> ValidationPolicy:
    return _global_policy


def validate_settings_with_policy(settings: Any, required: List[str],
                                  policy: Optional[ValidationPolicy] = None) -> None:
    """Presence check for required attributes; with type_check enabled, empty
    values also count as missing."""
    policy = policy or _global_policy
    if policy.type_check:
        missing = [k for k in required if not getattr(settings, k, None)]
    else:
        missing = [k for k in required if not hasattr(settings, k)]
    if missing:
        raise SettingsError(f"missing required settings: {', '.join(missing)}")


def validate_env_with_policy(names: List[str],
                             policy: Optional[ValidationPolicy] = None) -> Dict[str, Optional[str]]:
    """Require env vars; empty strings count as missing when type_check is on."""
    policy = policy or _global_policy
    out: Dict[str, Optional[str]] = {}
    missing: List[str] = []
    for n in names:
        v = os.environ.get(n)
        if v is None or (policy.type_check and v == ""):
            missing.append(n)
        else:
            out[n] = v
    if missing:
        raise SettingsError(f"missing env: {', '.join(missing)}")
    return out


def validate_and_serialize(settings, required: List[str],
                           serializer: Callable[[Any], Dict[str, Any]]) -> Dict[str, Any]:
    errors = get_missing_settings(settings, required)
    if errors:
        raise SettingsError(f"missing required settings: {', '.join(errors)}")
    return serializer(settings)


def validate_with_hooks(settings, required: List[str],
                        pre_hook: Callable[[Any], None],
                        post_hook: Callable[[], None]) -> None:
    """Run pre_hook(settings), validate, then ALWAYS run post_hook()."""
    pre_hook(settings)
    try:
        validate_settings(settings, required)
    finally:
        post_hook()


def bulk_validate_settings(settings_list: List[object], required: List[str]) -> List[SettingsError]:
    errors = []
    for settings in settings_list:
        try:
            validate_settings(settings, required)
        except SettingsError as e:
            errors.append(e)
    return errors


def get_missing_settings(settings, required: List[str]) -> List[str]:
    return [k for k in required if not hasattr(settings, k)]


def log_validation_errors(errors: List[SettingsError], level: str = "error") -> None:
    level_num = logging.getLevelName(level.upper())
    if not isinstance(level_num, int):
        level_num = logging.ERROR
    for error in errors:
        logger.log(level_num, "settings validation: %s", error)


def validate_settings(settings, required: list[str]) -> None:
    """Raise SettingsError if any required attribute is missing/empty."""
    missing = [k for k in required if not getattr(settings, k, None)]
    if missing:
        raise SettingsError("missing required settings: " + ", ".join(missing))


def require_env(*names: str) -> dict:
    out, missing = {}, []
    for n in names:
        v = os.environ.get(n)
        (out.__setitem__(n, v) if v else missing.append(n))
    if missing:
        raise SettingsError("missing env: " + ", ".join(missing))
    return out


def _selftest() -> None:
    from types import SimpleNamespace

    s = SimpleNamespace(database_url="sqlite://", secret_key="k", empty="")

    # nucleus: presence/empty checks
    validate_settings(s, ["database_url", "secret_key"])
    try:
        validate_settings(s, ["secret_key", "missing_one", "empty"])
        raise AssertionError("missing settings accepted")
    except SettingsError as e:
        assert "missing_one" in str(e) and "empty" in str(e)
        assert "sqlite://" not in str(e)  # keys only, never values

    # policy-driven variant: type_check off tolerates empty-but-present attrs
    validate_settings_with_policy(s, ["empty"], ValidationPolicy(type_check=False))
    try:
        validate_settings_with_policy(s, ["empty"], ValidationPolicy(type_check=True))
        raise AssertionError("empty accepted under type_check")
    except SettingsError:
        pass

    # global policy configuration is real (used when policy=None)
    configure_validation_policy(ValidationPolicy(type_check=False))
    assert get_validation_policy().type_check is False
    validate_settings_with_policy(s, ["empty"])  # passes under the new global
    configure_validation_policy(ValidationPolicy())
    try:
        validate_settings_with_policy(s, ["empty"])
        raise AssertionError("global policy not applied")
    except SettingsError:
        pass
    try:
        configure_validation_policy("nope")  # type: ignore[arg-type]
        raise AssertionError("non-policy accepted")
    except TypeError:
        pass

    # env validation (empty counts as missing under type_check)
    saved = {k: os.environ.get(k) for k in ("SV_A", "SV_B", "SV_EMPTY")}
    try:
        os.environ["SV_A"] = "1"
        os.environ["SV_EMPTY"] = ""
        os.environ.pop("SV_B", None)
        assert validate_env_with_policy(["SV_A"]) == {"SV_A": "1"}
        try:
            validate_env_with_policy(["SV_A", "SV_B", "SV_EMPTY"])
            raise AssertionError("missing env accepted")
        except SettingsError as e:
            assert "SV_B" in str(e) and "SV_EMPTY" in str(e)
        # type_check off: empty string is acceptable
        assert validate_env_with_policy(["SV_EMPTY"],
                                        ValidationPolicy(type_check=False)) == {"SV_EMPTY": ""}
        assert require_env("SV_A") == {"SV_A": "1"}
        try:
            require_env("SV_B")
            raise AssertionError("require_env missed")
        except SettingsError:
            pass
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # serialize-after-validate + hooks + bulk
    blob = validate_and_serialize(s, ["database_url"], lambda st: {"db": st.database_url})
    assert blob == {"db": "sqlite://"}
    try:
        validate_and_serialize(s, ["nope"], lambda st: {})
        raise AssertionError("serialize on invalid settings")
    except SettingsError:
        pass

    calls: list = []
    validate_with_hooks(s, ["database_url"],
                        pre_hook=lambda st: calls.append(("pre", st is s)),
                        post_hook=lambda: calls.append(("post", True)))
    assert calls == [("pre", True), ("post", True)]
    calls.clear()
    try:
        validate_with_hooks(s, ["missing"], pre_hook=lambda st: calls.append("pre"),
                            post_hook=lambda: calls.append("post"))
        raise AssertionError("invalid settings passed hooks")
    except SettingsError:
        assert calls == ["pre", "post"]  # post_hook ALWAYS runs

    good = SimpleNamespace(x=1)
    bad = SimpleNamespace()
    errs = bulk_validate_settings([good, bad, good], ["x"])
    assert len(errs) == 1 and isinstance(errs[0], SettingsError)
    assert get_missing_settings(bad, ["x", "y"]) == ["x", "y"]
    log_validation_errors(errs)  # logging path, no print, no raise
    log_validation_errors(errs, level="not-a-level")  # falls back safely

    print("settings_validation selftest: PASS")


if __name__ == "__main__":
    _selftest()
