"""
render — render.yaml blueprint.

### PART-META-JSON
{
  "name": "render",
  "layer": "deployment",
  "purpose": "render.yaml blueprint.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: render_config(*, project_name, env_vars, build_cmd); validate_render_config(config); render_yaml_from_config(config); render_yaml_with_template(template_path, **kwargs); render_yaml_with_env(*, env_vars); ServiceConfig(...); EnvConfig(...) (plus more).",
  "outputs": "Returns: render_config -> Dict[str, Any]; validate_render_config -> None; render_yaml_from_config -> str; render_yaml_with_template -> str; render_yaml_with_env -> str.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import `render_config` from `scrapyard.deployment.render` and call it as shown in `example`; run `py -m scrapyard.deployment.render` to see its offline selftest.",
  "example": "from scrapyard.deployment.render import render_config",
  "import_path": "scrapyard.deployment.render"
}
### END-PART-META
"""
from __future__ import annotations
import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ValidationError
from jinja2 import Template

STATUS = "core"

class ServiceConfig(BaseModel):
    type: str
    name: str
    env: Optional[Dict[str, str]] = None
    buildCommand: Optional[str] = None
    startCommand: Optional[str] = None
    extraServices: Optional[List[Dict[str, Any]]] = None

class EnvConfig(BaseModel):
    project_name: str
    env_vars: Dict[str, str]
    build_cmd: str

def render_config(*, project_name: str, env_vars: Dict[str, str], build_cmd: str) -> Dict[str, Any]:
    return {
        "project_name": project_name,
        "env_vars": env_vars,
        "build_cmd": build_cmd
    }

def validate_render_config(config: Dict[str, Any]) -> None:
    EnvConfig(**config)

def render_yaml_from_config(config: Dict[str, Any]) -> str:
    template = """
services:
  - type: {{ service.type }}
    name: {{ service.name }}
    env: {{ service.env | tojson }}
    buildCommand: {{ service.buildCommand }}
    startCommand: {{ service.startCommand }}
    extraServices: {{ service.extraServices | tojson }}
"""
    # Backward compatibility: if config is not structured with "services", assume the old format
    if "services" not in config:
        config_service = {
            "type": "web",
            "name": config.get("name", "app"),
            "env": config.get("env", {}),
            "buildCommand": config.get("buildCommand"),
            "startCommand": config.get("startCommand"),
            "extraServices": config.get("extraServices")
        }
    else:
        config_service = {
            "type": config["services"][0]["type"],
            "name": config["services"][0]["name"],
            "env": config["services"][0].get("env", {}),
            "buildCommand": config["services"][0].get("buildCommand"),
            "startCommand": config["services"][0].get("startCommand"),
            "extraServices": config["services"][0].get("extraServices")
        }
    jinja_template = Template(template)
    return jinja_template.render(service=config_service)

def render_yaml_with_template(template_path: str, **kwargs) -> str:
    with open(template_path, 'r') as file:
        template_content = file.read()
    jinja_template = Template(template_content)
    return jinja_template.render(**kwargs)

def render_yaml_with_env(*, env_vars: Optional[Dict[str, str]] = None) -> str:
    if env_vars is None:
        env_vars = {}
    config = EnvConfig(
        project_name="app",
        env_vars=env_vars,
        build_cmd="pip install -r requirements.txt"
    )
    return render_yaml_from_config(config.dict())

def render_yaml_with_metrics(*, metrics: Optional[Dict[str, Any]] = None) -> str:
    if metrics is None:
        metrics = {}
    config = EnvConfig(
        project_name="app",
        env_vars={},
        build_cmd="pip install -r requirements.txt"
    )
    return render_yaml_from_config(config.dict())

def render_yaml_with_audit(*, audit: Optional[Dict[str, Any]] = None) -> str:
    if audit is None:
        audit = {}
    config = EnvConfig(
        project_name="app",
        env_vars={},
        build_cmd="pip install -r requirements.txt"
    )
    return render_yaml_from_config(config.dict())

def render_yaml_with_bulk_services(services: List[Dict[str, Any]]) -> str:
    if not services:
        raise ValueError("At least one service must be provided")
    config = {
        "services": [
            ServiceConfig(**service).dict() for service in services
        ]
    }
    return render_yaml_from_config(config)

def render_yaml(*, name: str = "app", start: str = "uvicorn main:app --host 0.0.0.0 --port $PORT", env_vars: Optional[Dict[str, str]] = None, build_cmd: Optional[str] = None, extra_services: Optional[List[Dict[str, Any]]] = None) -> str:
    if env_vars is None:
        env_vars = {}
    if build_cmd is None:
        build_cmd = "pip install -r requirements.txt"
    config_service = ServiceConfig(
        type="web",
        name=name,
        env=env_vars,
        buildCommand=build_cmd,
        startCommand=start,
        extraServices=extra_services
    )
    return render_yaml_from_config(config_service.dict())


def _selftest() -> None:
    import yaml
    y = render_yaml(name="myapp", start="uvicorn main:app", env_vars={"KEY": "val"})
    doc = yaml.safe_load(y)  # must be valid YAML
    svc = doc["services"][0]
    assert svc["type"] == "web" and svc["name"] == "myapp"
    assert svc["startCommand"] == "uvicorn main:app"
    assert svc["env"] == {"KEY": "val"}
    # config helper
    cfg = render_config(project_name="p", env_vars={}, build_cmd="pip install")
    assert cfg["project_name"] == "p" and cfg["build_cmd"] == "pip install"
    # NEGATIVE: EnvConfig validation rejects a config missing required fields
    from pydantic import ValidationError
    try:
        validate_render_config({"project_name": "p"})
        raise AssertionError("incomplete config accepted")
    except ValidationError:
        pass
    # NEGATIVE: bulk services requires at least one service
    try:
        render_yaml_with_bulk_services([])
        raise AssertionError("empty service list accepted")
    except ValueError:
        pass
    print("render selftest OK")


if __name__ == "__main__":
    _selftest()
