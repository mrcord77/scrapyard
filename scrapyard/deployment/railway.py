"""
railway — Railway service + variables config.

### PART-META-JSON
{
  "name": "railway",
  "layer": "deployment",
  "purpose": "Railway service + variables config.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: railway_json(*, start, env, secrets); get_railway_config(); set_railway_config(config); validate_railway_config(config); apply_railway_config(config); RailwayConfig(...); ConfigValidationError(...); SecretInjectionError(...) (plus more).",
  "outputs": "Returns: railway_json -> str; get_railway_config -> Dict[str, Any]; set_railway_config -> None; validate_railway_config -> List[Dict[str, str]]; apply_railway_config -> str.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import `railway_json` from `scrapyard.deployment.railway` and call it as shown in `example`; run `py -m scrapyard.deployment.railway` to see its offline selftest.",
  "example": "from scrapyard.deployment.railway import railway_json",
  "import_path": "scrapyard.deployment.railway"
}
### END-PART-META
"""
from __future__ import annotations
import json
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, ConfigDict, ValidationError

STATUS = "core"

class RailwayConfig(BaseModel):
    build: Dict[str, Any] = {"builder": "NIXPACKS"}
    deploy: Dict[str, Any] = {"startCommand": "uvicorn main:app --host 0.0.0.0 --port $PORT", "restartPolicyType": "ON_FAILURE"}

    model_config = ConfigDict(extra="forbid")

class ConfigValidationError(ValidationError):
    pass

class SecretInjectionError(Exception):
    pass
class RailwayConfigFileError(Exception):
    pass

def railway_json(
    *,
    start: str = "uvicorn main:app --host 0.0.0.0 --port $PORT",
    env: Optional[Dict[str, str]] = None,
    secrets: Optional[Dict[str, str]] = None
) -> str:
    config = RailwayConfig(deploy={"startCommand": start})
    if env is not None:
        apply_env_to_railway(config=config, env=env)
    if secrets is not None:
        apply_secrets_to_railway(config=config, secrets=secrets)
    return json.dumps(config.model_dump(), indent=2)

def get_railway_config() -> Dict[str, Any]:
    return RailwayConfig().model_dump()

def set_railway_config(config: Dict[str, Any]) -> None:
    try:
        config = RailwayConfig(**config)
    except ValidationError as e:
        raise ConfigValidationError(e.errors())
    else:
        RailwayConfig.update_from_dict(config.model_dump())

def validate_railway_config(config: Dict[str, Any]) -> List[Dict[str, str]]:
    try:
        config = RailwayConfig(**config)
    except ValidationError as e:
        return e.errors()
    return []

def apply_railway_config(config: Dict[str, Any]) -> str:
    set_railway_config(config)
    return railway_json()

def export_railway_config(path: str) -> None:
    try:
        with open(path, 'w') as f:
            json.dump(get_railway_config(), f, indent=2)
    except IOError as e:
        raise RailwayConfigFileError(f"Failed to write config file: {e}")

def import_railway_config(path: str) -> Dict[str, Any]:
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        raise RailwayConfigFileError(f"Failed to read config file: {e}")

def apply_env_to_railway(config: Dict[str, Any], env: Dict[str, str]) -> None:
    try:
        config = RailwayConfig(**config)
        for key, value in env.items():
            if key in config.model_fields:
                setattr(config, key, value)
    except ValidationError as e:
        raise ConfigValidationError(e.errors())

def apply_secrets_to_railway(config: Dict[str, Any], secrets: Dict[str, str]) -> None:
    try:
        config = RailwayConfig(**config)
        for key, value in secrets.items():
            if key in config.model_fields:
                setattr(config, key, value)
    except ValidationError as e:
        raise ConfigValidationError(e.errors())

def generate_railway_env() -> Dict[str, str]:
    config = get_railway_config()
    env_vars = {k: v for k, v in config.items() if isinstance(v, str)}
    return env_vars


def _selftest() -> None:
    # railway_json produces valid JSON with the expected start command
    s = railway_json(start="uvicorn app:api --host 0.0.0.0 --port $PORT")
    doc = json.loads(s)
    assert doc["deploy"]["startCommand"] == "uvicorn app:api --host 0.0.0.0 --port $PORT"
    assert doc["build"]["builder"] == "NIXPACKS"
    # default config carries both sections
    cfg = get_railway_config()
    assert "build" in cfg and "deploy" in cfg
    # a well-formed config validates clean
    assert validate_railway_config(
        {"build": {"builder": "NIXPACKS"}, "deploy": {"startCommand": "x"}}
    ) == []
    # NEGATIVE: extra="forbid" rejects unknown fields
    errs = validate_railway_config({"bogus_field": 1})
    assert len(errs) > 0
    print("railway selftest OK")


if __name__ == "__main__":
    _selftest()
