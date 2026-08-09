"""
openapi_custom — Customize OpenAPI schema, tags, security schemes.

### PART-META-JSON
{
  "name": "openapi_custom",
  "layer": "api",
  "purpose": "OpenAPI schema customization for FastAPI apps: info block (title/version/description/contact), tags with external docs, security schemes (oauth2/api_key), servers and base path, OpenAPI version override, Swagger UI / ReDoc options, custom components, and arbitrary schema hooks — assembled lazily and cached on the app.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "A FastAPI app plus declarative customizations (tags, schemes, servers, hooks).",
  "outputs": "A cached, customized OpenAPI schema served at /openapi.json.",
  "files_created": [],
  "security_notes": "Declaring a security scheme here only DOCUMENTS it — enforcement still comes from your auth dependencies; never assume a documented scheme is applied. The generated schema is public at /openapi.json by default: keep internal server URLs, staging hosts, and secret-bearing examples out of servers/components, or disable docs routes in production.",
  "ai_usage": "custom = OpenAPICustomization(app); custom.set_openapi_info(...); custom.add_security_scheme(...); custom() to apply.",
  "example": "OpenAPICustomization(app).set_openapi_info('svc', '2.0.0', 'desc'); customize_openapi(app, title='svc')",
  "import_path": "scrapyard.api.openapi_custom"
}
### END-PART-META
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import fastapi.openapi.utils as openapi_utils
from fastapi import FastAPI

STATUS = "core"


class OpenAPICustomization:
    def __init__(self, app: FastAPI):
        self.app = app
        self.openapi_schema: Optional[Dict[str, Any]] = None
        self._tags: List[Dict[str, Any]] = []
        self._security_schemes: Dict[str, Dict[str, Any]] = {}
        self._schema_hooks: List[Callable[[Dict], Dict]] = []
        self._ui_config: Dict[str, Any] = {}
        self._openapi_version: Optional[str] = None
        self._base_path = "/"
        self._external_docs: List[Dict[str, str]] = []
        self._info: Dict[str, Any] = {
            "title": app.title,
            "version": "1.0.0",
            "description": "",
            "contact": None,
        }
        self._servers: List[Dict[str, str]] = []
        self._components: Dict[str, Dict] = {}

    def add_openapi_tag(self, tag: str, description: str,
                        external_docs: Optional[Dict[str, str]] = None) -> None:
        """Add a reusable tag with metadata (duplicates by name are ignored)."""
        if any(t["name"] == tag for t in self._tags):
            return
        entry: Dict[str, Any] = {"name": tag, "description": description}
        if external_docs:
            entry["externalDocs"] = external_docs
        self._tags.append(entry)

    def add_security_scheme(self, name: str, scheme: str, description: str,
                            flows: Optional[Dict] = None) -> None:
        """Register a security scheme. Supported: 'oauth2' (requires flows),
        'api_key' (documented as header apiKey). Documentation only — enforcement
        still comes from your dependencies."""
        if scheme not in ("oauth2", "api_key"):
            raise ValueError(f"Unsupported security scheme type: {scheme}")
        if scheme == "oauth2":
            if not flows:
                raise ValueError("oauth2 scheme requires flows")
            self._security_schemes[name] = {"type": "oauth2", "description": description,
                                            "flows": flows}
        else:
            self._security_schemes[name] = {"type": "apiKey", "in": "header",
                                            "name": name, "description": description}

    def register_openapi_schema_hook(self, hook: Callable[[Dict], Dict]) -> None:
        """Register a hook(schema) -> schema applied when the schema is built."""
        if not callable(hook):
            raise TypeError("hook must be callable")
        self._schema_hooks.append(hook)

    def set_openapi_ui_config(self, config: Dict[str, Any]) -> None:
        """Configure the docs UIs: 'swagger_ui_parameters' are applied to the app
        (FastAPI passes them to Swagger UI); 'redoc_options' are embedded in the
        schema under the x-redoc-options vendor extension."""
        self._ui_config = dict(config)
        params = self._ui_config.get("swagger_ui_parameters")
        if params:
            merged = dict(getattr(self.app, "swagger_ui_parameters", None) or {})
            merged.update(params)
            self.app.swagger_ui_parameters = merged

    def set_openapi_version(self, version: str) -> None:
        if not version.startswith("3."):
            raise ValueError(f"Unsupported OpenAPI version: {version}")
        self._openapi_version = version

    def set_openapi_base_path(self, path: str) -> None:
        """Set the base path (exposed as a server entry when no servers are set)."""
        if not path.startswith("/"):
            raise ValueError("base path must start with '/'")
        self._base_path = path

    def add_external_documentation(self, url: str, description: str) -> None:
        """Add external documentation. The first entry becomes the spec-level
        externalDocs object; extras go under x-external-docs."""
        self._external_docs.append({"url": url, "description": description})

    def set_openapi_info(self, title: str, version: str, description: str,
                         contact: Optional[Dict] = None) -> None:
        self._info.update({"title": title, "version": version,
                           "description": description, "contact": contact})

    def set_openapi_servers(self, servers: List[Dict[str, str]]) -> None:
        for server in servers:
            if "url" not in server:
                raise ValueError("each server entry needs a 'url'")
        self._servers = list(servers)

    def add_openapi_component(self, name: str, component: Dict) -> None:
        """Add a custom components section (e.g. 'responses', 'parameters')."""
        if name in ("components", "tags"):
            raise ValueError(f"Component name conflict with reserved keyword: {name}")
        self._components[name] = component

    def _custom_openapi(self) -> Dict[str, Any]:
        servers = self._servers or (
            [{"url": self._base_path}] if self._base_path != "/" else None)
        openapi_schema = openapi_utils.get_openapi(
            title=self._info["title"],
            version=self._info["version"],
            description=self._info["description"] or None,
            contact=self._info["contact"],
            routes=self.app.routes,
            servers=servers,
        )
        if self._openapi_version:
            openapi_schema["openapi"] = self._openapi_version
        if self._tags:
            openapi_schema["tags"] = self._tags
        components = openapi_schema.setdefault("components", {})
        if self._security_schemes:
            components["securitySchemes"] = self._security_schemes
        for name, component in self._components.items():
            components[name] = component
        if self._external_docs:
            openapi_schema["externalDocs"] = self._external_docs[0]
            if len(self._external_docs) > 1:
                openapi_schema["x-external-docs"] = self._external_docs[1:]
        if self._ui_config.get("redoc_options"):
            openapi_schema["x-redoc-options"] = self._ui_config["redoc_options"]
        for hook in self._schema_hooks:
            openapi_schema = hook(openapi_schema)
        return openapi_schema

    def __call__(self) -> FastAPI:
        """Build (once) and install the customized schema on the app."""
        if not self.openapi_schema:
            self.openapi_schema = self._custom_openapi()
        self.app.openapi_schema = self.openapi_schema
        return self.app


# --- grafted from original part (API stability) ---
def customize_openapi(app, *, title=None, version=None, description=None):
    """Override the generated OpenAPI doc metadata."""
    from fastapi.openapi.utils import get_openapi
    def _schema():
        if app.openapi_schema: return app.openapi_schema
        s=get_openapi(title=title or app.title, version=version or "1.0.0",
                      description=description, routes=app.routes)
        app.openapi_schema=s; return s
    app.openapi=_schema; return app


def _selftest() -> None:
    from fastapi.testclient import TestClient

    app = FastAPI(title="orig")

    @app.get("/items", tags=["items"])
    def items():
        return []

    custom = OpenAPICustomization(app)
    custom.set_openapi_info("custom-api", "2.1.0", "A customized API",
                            contact={"name": "team", "email": "team@example.com"})
    custom.add_openapi_tag("items", "Item operations",
                           external_docs={"url": "https://docs.example.test/items"})
    custom.add_openapi_tag("items", "duplicate ignored")
    custom.add_security_scheme("X-API-Key", "api_key", "API key auth")
    custom.add_security_scheme("oauth", "oauth2", "OAuth2",
                               flows={"clientCredentials": {"tokenUrl": "/token", "scopes": {}}})
    for bad in [("basic", "http"), ]:
        try:
            custom.add_security_scheme(*bad, "desc")
            raise AssertionError("bad scheme accepted")
        except ValueError:
            pass
    try:
        custom.add_security_scheme("o2", "oauth2", "no flows")
        raise AssertionError("oauth2 without flows accepted")
    except ValueError:
        pass
    custom.set_openapi_version("3.1.0")
    try:
        custom.set_openapi_version("2.0")
        raise AssertionError("openapi 2.0 accepted")
    except ValueError:
        pass
    custom.set_openapi_base_path("/api/v2")
    custom.add_external_documentation("https://docs.example.test", "Main docs")
    custom.add_external_documentation("https://wiki.example.test", "Wiki")
    custom.add_openapi_component("responses", {"RateLimited": {"description": "429"}})
    try:
        custom.add_openapi_component("components", {})
        raise AssertionError("reserved component name accepted")
    except ValueError:
        pass
    custom.set_openapi_ui_config({"swagger_ui_parameters": {"docExpansion": "none"},
                                  "redoc_options": {"hideDownloadButton": True}})
    custom.register_openapi_schema_hook(
        lambda schema: {**schema, "x-hooked": True})

    custom()  # apply

    schema = app.openapi()
    assert schema["info"]["title"] == "custom-api" and schema["info"]["version"] == "2.1.0"
    assert schema["openapi"] == "3.1.0"
    assert [t["name"] for t in schema["tags"]] == ["items"]
    assert schema["components"]["securitySchemes"]["X-API-Key"]["type"] == "apiKey"
    assert "flows" in schema["components"]["securitySchemes"]["oauth"]
    assert schema["components"]["responses"]["RateLimited"]["description"] == "429"
    assert schema["externalDocs"]["url"] == "https://docs.example.test"
    assert schema["x-external-docs"][0]["url"] == "https://wiki.example.test"
    assert schema["servers"][0]["url"] == "/api/v2"
    assert schema["x-hooked"] is True
    assert schema["x-redoc-options"] == {"hideDownloadButton": True}
    assert app.swagger_ui_parameters["docExpansion"] == "none"

    # served at /openapi.json
    with TestClient(app) as client:
        assert client.get("/openapi.json").json()["info"]["title"] == "custom-api"

    # legacy helper
    app2 = FastAPI(title="legacy")
    customize_openapi(app2, title="renamed", version="9.9.9")
    assert app2.openapi()["info"] == {"title": "renamed", "version": "9.9.9"}

    print("openapi_custom selftest: PASS")


if __name__ == "__main__":
    _selftest()
