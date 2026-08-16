"""
routers — Convention for grouping/mounting versioned routers.

### PART-META-JSON
{
  "name": "routers",
  "layer": "api",
  "purpose": "Router conventions: make_router() builds an APIRouter with a consistent prefix and auto-derived tag (from the prefix), and register_all() mounts a list of routers onto an app in order.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Route prefix strings, tag lists, APIRouter instances.",
  "outputs": "Configured APIRouter instances; routers mounted on the app.",
  "files_created": [],
  "security_notes": "Pure wiring — no auth is added here. Route-level protection (Depends on auth/permissions) must be declared on the routers themselves; mounting order does not change FastAPI's route matching for distinct prefixes.",
  "ai_usage": "r = make_router('/v1/users'); r.get('/')(list_users); register_all(app, [r]).",
  "example": "router = make_router('/v1/orders'); register_all(app, [router])",
  "import_path": "scrapyard.api.routers"
}
### END-PART-META
"""
from __future__ import annotations

STATUS = "core"

def make_router(prefix: str = "", tags: list[str] | None = None):
    """Create a namespaced APIRouter with a consistent prefix/tags convention.
    With no explicit tags, the prefix (minus slashes) becomes the tag."""
    from fastapi import APIRouter
    return APIRouter(prefix=prefix, tags=tags or ([prefix.strip("/")] if prefix else []))

def register_all(app, routers: list) -> None:
    """Mount a list of routers onto an app (used by the app entrypoint)."""
    for r in routers:
        app.include_router(r)


def _selftest() -> None:
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    # prefix/tag conventions
    r = make_router("/v1/users")
    assert isinstance(r, APIRouter)
    assert r.prefix == "/v1/users" and r.tags == ["v1/users"]
    r2 = make_router("/v1/orders", tags=["orders"])
    assert r2.tags == ["orders"]
    bare = make_router()
    assert bare.prefix == "" and bare.tags == []

    @r.get("/")
    def list_users():
        return ["u1"]

    @r2.get("/")
    def list_orders():
        return ["o1"]

    app = FastAPI()
    register_all(app, [r, r2])
    with TestClient(app) as client:
        assert client.get("/v1/users/").json() == ["u1"]
        assert client.get("/v1/orders/").json() == ["o1"]
        # tags surface in the OpenAPI schema
        schema = client.get("/openapi.json").json()
        assert schema["paths"]["/v1/users/"]["get"]["tags"] == ["v1/users"]
        assert schema["paths"]["/v1/orders/"]["get"]["tags"] == ["orders"]

    print("routers selftest: PASS")


if __name__ == "__main__":
    _selftest()
