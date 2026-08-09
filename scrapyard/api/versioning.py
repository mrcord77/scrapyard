"""
versioning — URL/header API versioning helpers.

### PART-META-JSON
{
  "name": "versioning",
  "layer": "api",
  "purpose": "API versioning toolkit: version extraction from /v{n} paths or the X-Version header, allow-list validation, VersionedRouter (an APIRouter pinned to /v{version}), variants adding dependency-style middleware, custom prefixes, request-body serializers, startup/shutdown hooks, or dict config, bulk router creation, and Deprecation/Sunset response headers.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi",
    "pydantic"
  ],
  "inputs": "Version strings, request objects, router options, an allowed-version list.",
  "outputs": "Configured APIRouter instances; version/deprecation response headers.",
  "files_created": [],
  "security_notes": "Version strings are parsed with a digits-and-dots pattern, so arbitrary path segments cannot masquerade as versions, and unknown versions are rejected against an explicit allow-list (fail-closed) rather than routed to a default. The X-Version header is client-controlled: validate it before branching on it. Deprecation/Sunset headers are advisory only — removing a version means removing its router.",
  "ai_usage": "router = versioned_router('1.0'); or VersionedRouter('2.0') for allow-list enforcement; deprecate(response, sunset='2026-12-31') on old versions.",
  "example": "app.include_router(VersionedRouter('1.0')); v = get_version_from_request(request)",
  "import_path": "scrapyard.api.versioning"
}
### END-PART-META
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Type

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

STATUS = "core"


class VersionNotSupported(Exception):
    def __init__(self, version: str):
        self.version = version
        super().__init__(f"Version {version} is not supported.")

class VersionParsingError(Exception):
    def __init__(self, header: Optional[str], path: Optional[str]):
        self.header = header
        self.path = path
        super().__init__(f"Failed to parse version from header: {header}, or path: {path}")

class VersionAlreadyExists(Exception):
    def __init__(self, version: str):
        self.version = version
        super().__init__(f"Router for version {version} already exists.")

class MiddlewareRegistrationError(Exception):
    def __init__(self, middleware):
        self.middleware = middleware
        super().__init__(f"Failed to register middleware: {middleware}")

class SerializerNotRegistered(Exception):
    def __init__(self, serializer: Type[BaseModel]):
        self.serializer = serializer
        super().__init__(f"Serializer {serializer} is not registered for this version.")


ALLOWED_API_VERSIONS: List[str] = ["1.0", "2.0"]
DEFAULT_VERSION_PREFIX = "/v{version}"
DEPRECATION_HEADER_ENABLED = True

_VERSION_PATH_RE = re.compile(r"/v(?P<version>\d+(?:\.\d+)*)(?:/|$)")


def set_allowed_versions(versions: List[str]) -> None:
    """Replace the module-wide version allow-list."""
    global ALLOWED_API_VERSIONS
    if not versions:
        raise ValueError("allowed versions must not be empty")
    ALLOWED_API_VERSIONS = list(versions)


def get_version_from_request(request: Request) -> str | None:
    """Extract the API version from a /v{n[.n]} path segment, else the
    X-Version header, else None. Only digits-and-dots count as versions."""
    path_match = _VERSION_PATH_RE.search(request.url.path)
    if path_match:
        return path_match.group("version")
    header = request.headers.get("X-Version")
    if header:
        return header
    return None


def validate_version(version: str, allowed_versions: List[str]) -> str:
    if version not in allowed_versions:
        raise VersionNotSupported(version)
    return version


class VersionedRouter(APIRouter):
    """APIRouter pinned to /v{version}; the version must be on the allow-list."""

    def __init__(self, version: str, *, prefix: Optional[str] = None, **kwargs):
        self.version = validate_version(version, ALLOWED_API_VERSIONS)
        full_prefix = f"{prefix.rstrip('/')}/v{self.version}" if prefix else f"/v{self.version}"
        kwargs.setdefault("tags", [f"v{self.version}"])
        super().__init__(prefix=full_prefix, **kwargs)


def versioned_router_with_middleware(version: str, middleware: List[Callable], **kwargs) -> APIRouter:
    """Versioned router whose routes all run the given callables as dependencies
    (FastAPI's router-level mechanism; APIRouter has no ASGI middleware slot)."""
    if not isinstance(middleware, list):
        raise MiddlewareRegistrationError(middleware)
    for mw in middleware:
        if not callable(mw):
            raise MiddlewareRegistrationError(mw)
    deps = list(kwargs.pop("dependencies", []) or [])
    deps.extend(Depends(mw) for mw in middleware)
    return VersionedRouter(version, dependencies=deps, **kwargs)


def versioned_router_with_prefix(version: str, prefix: str, **kwargs) -> APIRouter:
    """Versioned router mounted under an extra prefix: {prefix}/v{version}."""
    if not prefix.startswith("/"):
        raise ValueError("Prefix must start with '/'")
    return VersionedRouter(version, prefix=prefix, **kwargs)


def bulk_versioned_router(versions: List[str], **kwargs) -> List[APIRouter]:
    routers: List[VersionedRouter] = []
    for version in versions:
        if any(router.version == version for router in routers):
            raise VersionAlreadyExists(version)
        routers.append(VersionedRouter(version, **kwargs))
    return routers


def versioned_response(response: Response, version: str, deprecate: bool = False,
                       sunset: Optional[str] = None) -> Response:
    response.headers["X-Version"] = version
    if DEPRECATION_HEADER_ENABLED and deprecate:
        response.headers["Deprecation"] = "true"
        if sunset:
            response.headers["Sunset"] = sunset
    return response


def versioned_router_with_serializer(version: str, serializer: Type[BaseModel], **kwargs) -> APIRouter:
    """Versioned router that validates JSON bodies of write requests against
    ``serializer`` via a router-level dependency (400-style errors surface as
    SerializerNotRegistered -> FastAPI 500 unless handled; routes can also read
    router.serializer to build response models)."""
    if not (isinstance(serializer, type) and issubclass(serializer, BaseModel)):
        raise SerializerNotRegistered(serializer)

    async def _validate_body(request: Request):
        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if body:
                try:
                    serializer.model_validate_json(body)
                except Exception as e:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=422,
                                        detail=f"body does not match {serializer.__name__}") from e

    deps = list(kwargs.pop("dependencies", []) or [])
    deps.append(Depends(_validate_body))
    router = VersionedRouter(version, dependencies=deps, **kwargs)
    router.serializer = serializer
    return router


def versioned_router_with_lifecycle_hooks(version: str, on_create: Callable,
                                          on_delete: Callable, **kwargs) -> APIRouter:
    """Versioned router firing on_create at app startup and on_delete at shutdown.
    Handlers are one-shot guarded (FastAPI can register router event handlers on
    both the router and the app, which would double-fire them otherwise)."""
    router = VersionedRouter(version, **kwargs)
    fired = {"up": False, "down": False}

    @router.on_event("startup")
    def _handle_on_create():  # noqa: ANN202
        if not fired["up"]:
            fired["up"] = True
            on_create()

    @router.on_event("shutdown")
    def _handle_on_delete():  # noqa: ANN202
        if not fired["down"]:
            fired["down"] = True
            on_delete()

    return router


def versioned_router_with_config(config: Dict[str, str], **kwargs) -> APIRouter:
    """Build a versioned router from a config dict: {'version': '1.0',
    'prefix': '/api' (optional), 'tags': 'a,b' (optional)}."""
    if "version" not in config:
        raise KeyError("Config key version not found")
    version = config["version"]
    prefix = config.get("prefix")
    tags = [t.strip() for t in config["tags"].split(",")] if config.get("tags") else None
    if tags:
        kwargs.setdefault("tags", tags)
    if prefix:
        return versioned_router_with_prefix(version, prefix, **kwargs)
    return VersionedRouter(version, **kwargs)


# --- grafted from original part (API stability) ---
def versioned_router(version: str):
    """Create a router prefixed /v{version} for clean API versioning."""
    from fastapi import APIRouter
    return APIRouter(prefix=f"/v{version}", tags=[f"v{version}"])

def deprecate(response, *, sunset: str | None=None):
    response.headers["Deprecation"]="true"
    if sunset: response.headers["Sunset"]=sunset
    return response


def _selftest() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    set_allowed_versions(["1.0", "2.0"])

    # VersionedRouter is a real APIRouter with allow-list enforcement
    r1 = VersionedRouter("1.0")
    assert isinstance(r1, APIRouter) and r1.prefix == "/v1.0" and r1.version == "1.0"
    try:
        VersionedRouter("9.9")
        raise AssertionError("unsupported version accepted")
    except VersionNotSupported:
        pass

    @r1.get("/ping")
    def ping():
        return {"v": "1.0"}

    # middleware-as-dependencies actually run
    seen: list = []
    r2 = versioned_router_with_middleware("2.0", [lambda: seen.append("mw")])
    try:
        versioned_router_with_middleware("2.0", "not-a-list")  # type: ignore[arg-type]
        raise AssertionError("non-list middleware accepted")
    except MiddlewareRegistrationError:
        pass

    @r2.get("/ping")
    def ping2():
        return {"v": "2.0"}

    # serializer-validated router
    class Payload(BaseModel):
        name: str

    r3 = versioned_router_with_serializer("1.0", Payload, prefix="/api")
    assert r3.serializer is Payload and r3.prefix == "/api/v1.0"
    try:
        versioned_router_with_serializer("1.0", dict)  # type: ignore[arg-type]
        raise AssertionError("non-model serializer accepted")
    except SerializerNotRegistered:
        pass

    @r3.post("/things")
    async def create_thing(request: Request):
        return {"ok": True}

    # lifecycle hooks
    lifecycle: list = []
    r4 = versioned_router_with_lifecycle_hooks("2.0", lambda: lifecycle.append("up"),
                                               lambda: lifecycle.append("down"),
                                               prefix="/hooked")
    # config-driven
    r5 = versioned_router_with_config({"version": "1.0", "prefix": "/cfg", "tags": "alpha,beta"})
    assert r5.prefix == "/cfg/v1.0" and r5.tags == ["alpha", "beta"]
    try:
        versioned_router_with_config({"prefix": "/x"})
        raise AssertionError("config without version accepted")
    except KeyError:
        pass

    # bulk creation with duplicate detection
    routers = bulk_versioned_router(["1.0", "2.0"])
    assert [r.version for r in routers] == ["1.0", "2.0"]
    try:
        bulk_versioned_router(["1.0", "1.0"])
        raise AssertionError("duplicate version accepted")
    except VersionAlreadyExists:
        pass

    app = FastAPI()
    for r in (r1, r2, r3, r4):
        app.include_router(r)

    @app.get("/deprecated")
    def deprecated_route(response: Response):
        versioned_response(response, "1.0", deprecate=True, sunset="2026-12-31")
        return {}

    with TestClient(app) as client:
        assert lifecycle == ["up"]
        assert client.get("/v1.0/ping").json() == {"v": "1.0"}
        assert client.get("/v2.0/ping").json() == {"v": "2.0"}
        assert seen == ["mw"]  # dependency ran
        # serializer gate: bad body 422, good body passes
        assert client.post("/api/v1.0/things", json={"bogus": 1}).status_code == 422
        assert client.post("/api/v1.0/things", json={"name": "x"}).json() == {"ok": True}
        # deprecation headers
        r = client.get("/deprecated")
        assert r.headers["X-Version"] == "1.0"
        assert r.headers["Deprecation"] == "true" and r.headers["Sunset"] == "2026-12-31"
        # version extraction: real versions parse, lookalike paths don't
        req_scope = {"type": "http", "path": "/v2.0/ping", "headers": [],
                     "query_string": b"", "method": "GET", "server": ("t", 80), "scheme": "http"}
        assert get_version_from_request(Request(req_scope)) == "2.0"
        req_scope["path"] = "/values/list"
        assert get_version_from_request(Request(req_scope)) is None
        req_scope["headers"] = [(b"x-version", b"2.0")]
        assert get_version_from_request(Request(req_scope)) == "2.0"
    assert lifecycle == ["up", "down"]

    # validate_version + allow-list mutation
    assert validate_version("1.0", ALLOWED_API_VERSIONS) == "1.0"
    set_allowed_versions(["3.0"])
    assert VersionedRouter("3.0").version == "3.0"
    try:
        set_allowed_versions([])
        raise AssertionError("empty allow-list accepted")
    except ValueError:
        pass
    set_allowed_versions(["1.0", "2.0"])

    print("versioning selftest: PASS")


if __name__ == "__main__":
    _selftest()
