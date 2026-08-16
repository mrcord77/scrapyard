"""
cors — Configured CORS policy helper.

### PART-META-JSON
{
  "name": "cors",
  "layer": "security",
  "purpose": "Configured CORS policy helper.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Public API: configure_cors_policy(origins, allow_credentials, allow_methods, allow_headers, expose_headers, max_age, allow_private_networks, allow_any_origin); apply_cors_policy(request, response, policy); register_cors_policies(app, policies); load_cors_from_env(); validate_cors_config(config); CORSConfig(...); InvalidCORSConfig(...); CORSNotEnabled(...) (plus more).",
  "outputs": "Returns: configure_cors_policy -> CORSConfig; load_cors_from_env -> CORSConfig; serialize_cors_config -> dict; deserialize_cors_config -> CORSConfig.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `configure_cors_policy` from `scrapyard.security.cors` and call it as shown in `example`; run `py -m scrapyard.security.cors` to see its offline selftest.",
  "example": "from scrapyard.security.cors import configure_cors_policy",
  "import_path": "scrapyard.security.cors"
}
### END-PART-META
"""
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError
from typing import List, Optional, Union
import os
from datetime import datetime, timezone

_CORS_EVENTS = []

class CORSConfig(BaseModel):
    origins: List[str] = []
    allow_credentials: bool = True
    allow_methods: List[str] = ["*"]
    allow_headers: List[str] = ["*"]
    expose_headers: List[str] = []
    max_age: int = 0
    allow_private_networks: bool = False
    allow_any_origin: bool = False

class InvalidCORSConfig(Exception):
    pass

class CORSNotEnabled(Exception):
    pass

class CORSHeaderConflict(Exception):
    pass

class CORSOriginNotAllowed(Exception):
    pass

def configure_cors_policy(origins: Optional[List[str]] = None, 
                          allow_credentials: bool = True,
                          allow_methods: List[str] = ["*"],
                          allow_headers: List[str] = ["*"],
                          expose_headers: List[str] = [],
                          max_age: int = 0,
                          allow_private_networks: bool = False,
                          allow_any_origin: bool = False) -> CORSConfig:
    config = CORSConfig(
        origins=origins or [],
        allow_credentials=allow_credentials,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
        expose_headers=expose_headers,
        max_age=max_age,
        allow_private_networks=allow_private_networks,
        allow_any_origin=allow_any_origin
    )
    validate_cors_config(config)
    return config

def apply_cors_policy(request: Request, response: Response, policy: CORSConfig):
    if not policy.origins:
        return
    
    origins = set(policy.origins) | ({"*"} if policy.allow_any_origin else set())
    
    for origin in origins:
        if request.headers.get("Origin") == origin and "*" not in origins:
            break
    else:
        raise CORSOriginNotAllowed(f"Request origin {request.headers['Origin']} is not allowed.")
    
    response.headers["Access-Control-Allow-Origin"] = next(iter(origins))
    response.headers["Access-Control-Allow-Credentials"] = str(policy.allow_credentials).lower()
    response.headers["Access-Control-Allow-Methods"] = ", ".join(policy.allow_methods)
    response.headers["Access-Control-Allow-Headers"] = ", ".join(policy.allow_headers)
    if policy.expose_headers:
        response.headers["Access-Control-Expose-Headers"] = ", ".join(policy.expose_headers)
    if policy.max_age > 0:
        response.headers["Access-Control-Max-Age"] = str(policy.max_age)

def register_cors_policies(app: FastAPI, policies: List[CORSConfig]):
    for policy in policies:
        apply_cors_policy(Request({}), Response({}), policy)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=policy.origins or [],
            allow_credentials=policy.allow_credentials,
            allow_methods=policy.allow_methods,
            allow_headers=policy.allow_headers,
            expose_headers=policy.expose_headers,
            max_age=policy.max_age
        )

def load_cors_from_env() -> CORSConfig:
    origins = os.getenv("CORS_ORIGINS", "").split(",")
    allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true"
    allow_methods = os.getenv("CORS_ALLOW_METHODS", "*")
    allow_headers = os.getenv("CORS_ALLOW_HEADERS", "*")
    expose_headers = os.getenv("CORS_EXPOSE_HEADERS", "").split(",")
    max_age = int(os.getenv("CORS_MAX_AGE", 0))
    allow_private_networks = os.getenv("CORS_ALLOW_PRIVATE_NETWORKS", "false").lower() == "true"
    allow_any_origin = os.getenv("CORS_ALLOW_ANY_ORIGIN", "false").lower() == "true"

    return CORSConfig(
        origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=[m.strip() for m in allow_methods.split(",") if m],
        allow_headers=[h.strip() for h in allow_headers.split(",") if h],
        expose_headers=expose_headers,
        max_age=max_age,
        allow_private_networks=allow_private_networks,
        allow_any_origin=allow_any_origin
    )

def validate_cors_config(config: CORSConfig):
    if not config.origins and not config.allow_any_origin:
        raise CORSNotEnabled("No CORS policy defined and no origins allowed.")
    for header in ["allow_credentials", "allow_methods", "allow_headers"]:
        value = getattr(config, header)
        if isinstance(value, str) and "," in value:
            setattr(config, header, [h.strip() for h in value.split(",") if h])
    if not all(isinstance(o, str) for o in config.origins):
        raise InvalidCORSConfig("Origins must be a list of strings.")
    if not isinstance(config.allow_credentials, bool):
        raise InvalidCORSConfig("allow_credentials must be a boolean.")
    if not all(isinstance(m, str) for m in config.allow_methods):
        raise InvalidCORSConfig("allow_methods must be a list of strings.")
    if not all(isinstance(h, str) for h in config.allow_headers):
        raise InvalidCORSConfig("allow_headers must be a list of strings.")
    if not all(isinstance(h, str) for h in config.expose_headers):
        raise InvalidCORSConfig("expose_headers must be a list of strings.")

def serialize_cors_config(config: CORSConfig) -> dict:
    return {
        "origins": config.origins,
        "allow_credentials": config.allow_credentials,
        "allow_methods": config.allow_methods,
        "allow_headers": config.allow_headers,
        "expose_headers": config.expose_headers,
        "max_age": config.max_age,
        "allow_private_networks": config.allow_private_networks,
        "allow_any_origin": config.allow_any_origin
    }

def deserialize_cors_config(data: dict) -> CORSConfig:
    return CORSConfig(**data)

def log_cors_event(event_type: str, request: Request, response: Response, policy: CORSConfig):
    if event_type not in {"allowed", "blocked", "preflight"}:
        raise ValueError("unsupported CORS event type")
    event = {
        "event_type": event_type,
        "origin": request.headers.get("Origin"),
        "allowed_origins": list(policy.origins),
        "status_code": getattr(response, "status_code", None),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _CORS_EVENTS.append(event)
    return event


def _selftest() -> None:
    """Offline, falsifiable self-test of the CORS policy decision logic."""
    class _Headers(dict):
        # case-insensitive-ish shim is unnecessary; apply_cors_policy uses "Origin"
        pass

    class _Req:
        def __init__(self, origin):
            self.headers = _Headers()
            if origin is not None:
                self.headers["Origin"] = origin

    class _Resp:
        def __init__(self):
            self.headers = {}

    allowed = "https://good.example"
    policy = configure_cors_policy(origins=[allowed])

    # 1) an ALLOWED origin is reflected in the response header
    resp = _Resp()
    apply_cors_policy(_Req(allowed), resp, policy)
    assert resp.headers.get("Access-Control-Allow-Origin") == allowed, \
        "allowed origin must be reflected"

    # 2) NEGATIVE: a DISALLOWED origin raises and is NOT reflected
    resp2 = _Resp()
    raised = False
    try:
        apply_cors_policy(_Req("https://evil.example"), resp2, policy)
    except CORSOriginNotAllowed:
        raised = True
    assert raised, "disallowed origin must raise CORSOriginNotAllowed"
    assert "Access-Control-Allow-Origin" not in resp2.headers, \
        "disallowed origin must not be reflected"

    # 3) NEGATIVE: a config with no origins and no wildcard fails closed
    closed = False
    try:
        configure_cors_policy(origins=[])
    except CORSNotEnabled:
        closed = True
    assert closed, "empty CORS policy must fail closed (CORSNotEnabled)"

    # 4) serialize/deserialize round-trips the policy
    rt = deserialize_cors_config(serialize_cors_config(policy))
    assert rt.origins == [allowed] and rt.allow_credentials == policy.allow_credentials
    event = log_cors_event("allowed", _Req(allowed), resp, policy)
    assert event["origin"] == allowed and _CORS_EVENTS[-1] == event

    print("cors: OK (5 assertions incl. disallowed-origin + fail-closed negatives)")


# --- grafted from original part (API stability) ---
def install_cors(app, origins=None, *, allow_credentials=True):
    """Install CORS middleware. Defaults to no origins (must opt in explicitly)."""
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or [],
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


if __name__ == "__main__":
    _selftest()

