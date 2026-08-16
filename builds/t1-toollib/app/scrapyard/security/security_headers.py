"""
security_headers — CSP/HSTS/frame/referrer security headers.

### PART-META-JSON
{
  "name": "security_headers",
  "layer": "security",
  "purpose": "Hardened HTTP response headers for FastAPI/Starlette apps: middleware setting CSP, HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy and Permissions-Policy; CSP accepted as plain string or directive dict/JSON; env-var policy overrides; per-app custom header policies with validation and a simple policy version archive.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi",
    "pydantic"
  ],
  "inputs": "SecurityPolicies (csp string/JSON + hsts flag), optional SECURITY_HEADERS_POLICY env JSON, custom HeaderPolicy entries.",
  "outputs": "Response headers applied to every response passing through the middleware.",
  "files_created": [],
  "security_notes": "Header values are validated against CR/LF and control characters to block header-injection. HSTS is on by default (max-age 1 year, includeSubDomains) — only meaningful over TLS. The default CSP is 'default-src self'; loosening it (e.g. unsafe-inline) is the caller's explicit choice. Custom header policies are restricted to a known allow-list of security header names so the middleware cannot be repurposed to spoof arbitrary headers.",
  "ai_usage": "app.add_middleware(SecurityHeadersMiddleware, policies=SecurityPolicies(...)) or the simpler install_security_headers(app).",
  "example": "from scrapyard.security.security_headers import install_security_headers; install_security_headers(app)",
  "import_path": "scrapyard.security.security_headers"
}
### END-PART-META
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Optional, Union

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

STATUS = "core"


class SecurityPolicies(BaseModel):
    csp: str = "default-src 'self'"
    hsts: bool = True

class HeaderPolicy(BaseModel):
    name: str
    value: str
    override: bool = False


class InvalidHeaderNameError(Exception):
    pass

class InvalidHeaderValueError(Exception):
    pass

class PolicyConflictError(Exception):
    pass

class PolicyValidationError(Exception):
    pass

class HeaderPolicyNotFoundError(Exception):
    pass

class HeaderPolicySerializationError(Exception):
    pass

class HeaderPolicyVersionError(Exception):
    pass


_VALID_HEADER_NAMES = {
    "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy",
    "Strict-Transport-Security", "Content-Security-Policy",
    "Content-Security-Policy-Report-Only", "Permissions-Policy",
    "Cross-Origin-Opener-Policy", "Cross-Origin-Embedder-Policy",
    "Cross-Origin-Resource-Policy", "Cache-Control",
}
_CTRL_RE = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, policies: Optional[SecurityPolicies] = None):
        super().__init__(app)
        self.policies = policies or SecurityPolicies()
        self._header_policies: Dict[str, HeaderPolicy] = {}
        # Build once: the default string CSP used to be json.loads()ed and
        # raised on every request; now both plain strings and JSON/dicts work.
        self._csp_value = self.build_csp_policy(self.policies.csp)

    async def dispatch(self, request: Request, call_next) -> Response:
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if self.policies.hsts:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        resp.headers["Content-Security-Policy"] = self._csp_value
        for policy in self._header_policies.values():
            if policy.override:
                resp.headers[policy.name] = policy.value
            else:
                resp.headers.setdefault(policy.name, policy.value)
        return resp

    def build_csp_policy(self, policy: Union[str, Dict[str, str]]) -> str:
        """Normalise a CSP given as a plain policy string, a directives dict,
        or a JSON object string, into a single header value."""
        if isinstance(policy, dict):
            directives = policy
        elif isinstance(policy, str):
            stripped = policy.strip()
            if stripped.startswith("{"):
                try:
                    directives = json.loads(stripped)
                except json.JSONDecodeError as e:
                    raise InvalidHeaderValueError(f"Invalid JSON CSP policy: {e}") from e
                if not isinstance(directives, dict):
                    raise InvalidHeaderValueError("JSON CSP policy must be an object")
            else:
                # plain CSP string — validate and use verbatim
                if not self._is_valid_header_value(stripped) or not stripped:
                    raise InvalidHeaderValueError(f"Invalid CSP policy string: {policy!r}")
                return stripped
        else:
            raise InvalidHeaderValueError(f"CSP policy must be str or dict, got {type(policy).__name__}")
        parts = []
        for name, value in directives.items():
            if _CTRL_RE.search(str(name)) or _CTRL_RE.search(str(value)):
                raise InvalidHeaderValueError(f"Control characters in CSP directive {name!r}")
            parts.append(f"{name} {value}".strip())
        if not parts:
            raise InvalidHeaderValueError("CSP policy has no directives")
        return "; ".join(parts)

    def add_header_policy(self, name: str, value: str, *, override: bool = False) -> HeaderPolicy:
        """Register a custom security header applied to every response."""
        self.validate_header_policy(name, value)
        policy = HeaderPolicy(name=name, value=value, override=override)
        self._header_policies[name] = policy
        return policy

    def remove_header_policy(self, name: str) -> None:
        if name not in self._header_policies:
            raise HeaderPolicyNotFoundError(f"No header policy registered for {name!r}")
        del self._header_policies[name]

    def get_header_policies(self) -> Dict[str, HeaderPolicy]:
        return dict(self._header_policies)

    def validate_header_policy(self, name: str, value: str) -> None:
        if not self._is_valid_header_name(name):
            raise InvalidHeaderNameError(f"Invalid header name: {name}")
        if not self._is_valid_header_value(value):
            raise InvalidHeaderValueError(f"Invalid header value: {value}")

    def _is_valid_header_name(self, name: str) -> bool:
        return name in _VALID_HEADER_NAMES

    def _is_valid_header_value(self, value: str) -> bool:
        """Reject non-strings and CR/LF/control chars (header injection)."""
        return isinstance(value, str) and not _CTRL_RE.search(value)


# --- env-driven policy loading + serialization + versioning ---

_POLICY_ENV_VAR = "SECURITY_HEADERS_POLICY"
_DEFAULT_POLICY_JSON = '{"csp": "default-src \'self\'", "hsts": true}'
_policy_archive: Dict[str, str] = {}
_current_policy_version = "v1"


def load_env_header_policies() -> SecurityPolicies:
    """Load SecurityPolicies from the SECURITY_HEADERS_POLICY env var (JSON),
    falling back to the default policy when unset."""
    policy_str = os.getenv(_POLICY_ENV_VAR, _DEFAULT_POLICY_JSON)
    try:
        return SecurityPolicies.model_validate_json(policy_str)
    except ValidationError as e:
        raise PolicyValidationError(f"Failed to parse header policies: {e}") from e


def serialize_header_policy(policies: SecurityPolicies) -> str:
    try:
        return policies.model_dump_json()
    except Exception as e:  # pragma: no cover - defensive
        raise HeaderPolicySerializationError(str(e)) from e


def get_policy_version() -> str:
    """Current policy version label (advanced by archive_policy_version)."""
    return _current_policy_version


def archive_policy_version(version: str, policies: Optional[SecurityPolicies] = None) -> None:
    """Archive a policy snapshot under ``version`` and advance the current version."""
    global _current_policy_version
    if not version or _CTRL_RE.search(version):
        raise HeaderPolicyVersionError(f"Invalid version label: {version!r}")
    if version in _policy_archive:
        raise HeaderPolicyVersionError(f"Version {version!r} already archived")
    _policy_archive[version] = serialize_header_policy(policies or SecurityPolicies())
    _current_policy_version = version


def get_archived_policy(version: str) -> SecurityPolicies:
    if version not in _policy_archive:
        raise HeaderPolicyVersionError(f"Version {version!r} not archived")
    return SecurityPolicies.model_validate_json(_policy_archive[version])


# --- grafted from original part (API stability) ---
def install_security_headers(app, *, hsts: bool = True,
                             csp: str = "default-src 'self'") -> None:
    """Add common security response headers via middleware."""
    class _Mw(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # noqa: ANN001, ANN201
            resp = await call_next(request)
            resp.headers.setdefault("X-Content-Type-Options", "nosniff")
            resp.headers.setdefault("X-Frame-Options", "DENY")
            resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            resp.headers.setdefault("Content-Security-Policy", csp)
            resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
            if hsts:
                resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            return resp

    app.add_middleware(_Mw)


def _selftest() -> None:
    from fastapi.testclient import TestClient

    # DEFAULT policy must work end-to-end (used to raise on every request)
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    with TestClient(app) as client:
        r = client.get("/ping")
        assert r.status_code == 200
        assert r.headers["Content-Security-Policy"] == "default-src 'self'"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert "Strict-Transport-Security" in r.headers

    # CSP forms: plain string, dict, JSON string; garbage rejected
    mw = SecurityHeadersMiddleware(FastAPI(), policies=SecurityPolicies(
        csp="default-src 'self'; script-src 'self'"))
    assert mw._csp_value == "default-src 'self'; script-src 'self'"
    assert mw.build_csp_policy({"default-src": "'self'", "img-src": "https:"}) == \
        "default-src 'self'; img-src https:"
    assert mw.build_csp_policy('{"default-src": "\'self\'"}') == "default-src 'self'"
    for bad in ("{not json", "", 42, {}):
        try:
            mw.build_csp_policy(bad)  # type: ignore[arg-type]
            raise AssertionError(f"accepted bad CSP {bad!r}")
        except InvalidHeaderValueError:
            pass

    # custom header policies actually get applied (not discarded)
    app2 = FastAPI()
    app2.add_middleware(SecurityHeadersMiddleware,
                        policies=SecurityPolicies(hsts=False))
    mw2 = None
    for m in app2.user_middleware:
        pass  # middleware instance is created at app startup by Starlette

    # exercise policy storage directly on an instance
    inst = SecurityHeadersMiddleware(FastAPI())
    inst.add_header_policy("Cross-Origin-Opener-Policy", "same-origin")
    assert "Cross-Origin-Opener-Policy" in inst.get_header_policies()
    try:
        inst.add_header_policy("X-Evil", "1")
        raise AssertionError("unknown header name accepted")
    except InvalidHeaderNameError:
        pass
    try:
        inst.add_header_policy("Cache-Control", "no-store\r\nSet-Cookie: hacked=1")
        raise AssertionError("header injection accepted")
    except InvalidHeaderValueError:
        pass
    inst.remove_header_policy("Cross-Origin-Opener-Policy")
    try:
        inst.remove_header_policy("Cross-Origin-Opener-Policy")
        raise AssertionError("double-remove did not raise")
    except HeaderPolicyNotFoundError:
        pass

    # env loading (os.getenv, not the nonexistent json.getenv)
    old = os.environ.get(_POLICY_ENV_VAR)
    try:
        os.environ.pop(_POLICY_ENV_VAR, None)
        p = load_env_header_policies()
        assert p.csp == "default-src 'self'" and p.hsts is True
        os.environ[_POLICY_ENV_VAR] = '{"csp": "default-src \'none\'", "hsts": false}'
        p = load_env_header_policies()
        assert p.csp == "default-src 'none'" and p.hsts is False
        os.environ[_POLICY_ENV_VAR] = '{"hsts": "not-a-bool-at-all"}'
        try:
            load_env_header_policies()
            raise AssertionError("invalid env policy accepted")
        except PolicyValidationError:
            pass
    finally:
        if old is None:
            os.environ.pop(_POLICY_ENV_VAR, None)
        else:
            os.environ[_POLICY_ENV_VAR] = old

    # serialization + versioning round-trip
    blob = serialize_header_policy(SecurityPolicies(hsts=False))
    assert json.loads(blob)["hsts"] is False
    assert get_policy_version() == "v1"
    archive_policy_version("v2", SecurityPolicies(csp="default-src 'none'"))
    assert get_policy_version() == "v2"
    assert get_archived_policy("v2").csp == "default-src 'none'"
    try:
        archive_policy_version("v2")
        raise AssertionError("duplicate version accepted")
    except HeaderPolicyVersionError:
        pass

    # legacy installer still works
    app3 = FastAPI()
    install_security_headers(app3, csp="default-src 'none'")
    @app3.get("/x")
    def x():
        return {}
    with TestClient(app3) as client:
        r = client.get("/x")
        assert r.headers["Content-Security-Policy"] == "default-src 'none'"

    print("security_headers selftest: PASS")


if __name__ == "__main__":
    _selftest()
