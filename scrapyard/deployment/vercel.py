"""
vercel — vercel.json for frontend deploys.

### PART-META-JSON
{
  "name": "vercel",
  "layer": "deployment",
  "purpose": "vercel.json for frontend deploys.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: vercel_json(*, app, build_use, routes); VercelConfig(...).",
  "outputs": "Returns: vercel_json -> str.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import `vercel_json` from `scrapyard.deployment.vercel` and call it as shown in `example`; run `py -m scrapyard.deployment.vercel` to see its offline selftest.",
  "example": "from scrapyard.deployment.vercel import vercel_json",
  "import_path": "scrapyard.deployment.vercel"
}
### END-PART-META
"""
from __future__ import annotations
import json
from typing import List, Dict, Optional

STATUS = "core"

class VercelConfig:
    def __init__(self):
        self.builds: List[Dict[str, str]] = [{"src": "main.py", "use": "@vercel/python"}]
        self.routes: List[Dict[str, Optional[str]]] = [{"src": "/(.*)", "dest": "main.py"}]
        self.env_vars: Dict[str, str] = {}
        self.output_dir: str = "dist"
        self.deployment_settings: Dict[str, Optional[str]] = {"region": None, "team": None}
        self.build_command: Optional[str] = None
        self.build_env_vars: Dict[str, str] = {}

    def add_build(self, app: str, use: str = "@vercel/python") -> None:
        self.builds.append({"src": app, "use": use})

    def add_route(self, src: str, dest: str, method: Optional[str] = None) -> None:
        if not src or not dest:
            raise ValueError("Route source and destination must be provided.")
        route = {"src": src, "dest": dest}
        if method:
            route["method"] = method
        self.routes.append(route)

    def set_env_vars(self, env_vars: Dict[str, str]) -> None:
        for key, value in env_vars.items():
            if not key.isidentifier() or any(char.isspace() for char in key):
                raise ValueError(f"Invalid environment variable key: {key}")
            self.env_vars[key] = value

    def set_output_dir(self, output_dir: str = "dist") -> None:
        self.output_dir = output_dir

    def set_deployment_settings(self, region: Optional[str] = None, team: Optional[str] = None) -> None:
        if not (region or team):
            raise ValueError("At least one of region or team must be provided.")
        self.deployment_settings["region"] = region
        self.deployment_settings["team"] = team

    def set_build_command(self, command: Optional[str] = None) -> None:
        self.build_command = command

    def set_build_env_vars(self, env_vars: Dict[str, str]) -> None:
        for key, value in env_vars.items():
            if not key.isidentifier() or any(char.isspace() for char in key):
                raise ValueError(f"Invalid environment variable key: {key}")
            self.build_env_vars[key] = value

    def get_config(self) -> Dict[str, object]:
        return {
            "builds": self.builds,
            "routes": self.routes,
            "env": self.env_vars,
            "output_dir": self.output_dir,
            "deployment_settings": self.deployment_settings,
            "build_command": self.build_command,
            "build_env_vars": self.build_env_vars
        }

    def write_config(self, path: str = "vercel.json") -> None:
        config_dict = self.get_config()
        try:
            with open(path, 'w') as f:
                json.dump(config_dict, f, indent=2)
        except IOError as e:
            raise IOError(f"Failed to write vercel.json file: {e}")

def vercel_json(*, app: str = "main.py", build_use: str = "@vercel/python", routes: Optional[List[Dict[str, Optional[str]]]] = None) -> str:
    config = VercelConfig()
    config.add_build(app, use=build_use)
    if routes:
        for route in routes:
            config.add_route(route["src"], route["dest"], method=route.get("method"))
    return json.dumps({"builds": config.builds, "routes": config.routes}, indent=2)


def _selftest() -> None:
    import tempfile
    import os
    # vercel_json emits valid JSON with the python builder + catch-all route
    doc = json.loads(vercel_json(app="api.py"))
    assert any(b["src"] == "api.py" for b in doc["builds"])
    assert any(b["use"] == "@vercel/python" for b in doc["builds"])
    assert doc["routes"][0]["src"] == "/(.*)"
    # env var validation accepts identifiers
    c = VercelConfig()
    c.set_env_vars({"API_KEY": "x"})
    assert c.env_vars["API_KEY"] == "x"
    # NEGATIVE: invalid env var key rejected
    try:
        c.set_env_vars({"bad key": "x"})
        raise AssertionError("invalid env key accepted")
    except ValueError:
        pass
    # NEGATIVE: empty route source/dest rejected
    try:
        c.add_route("", "/dest")
        raise AssertionError("empty route accepted")
    except ValueError:
        pass
    # write_config round-trips valid JSON to disk
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        pth = os.path.join(d, "vercel.json")
        c.write_config(pth)
        with open(pth) as f:
            loaded = json.load(f)
        assert "builds" in loaded and "routes" in loaded
    print("vercel selftest OK")


if __name__ == "__main__":
    _selftest()
