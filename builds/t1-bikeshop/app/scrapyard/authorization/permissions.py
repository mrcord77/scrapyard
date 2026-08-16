"""
permissions — Permission checks + FastAPI require() dependency (RBAC).

### PART-META-JSON
{
  "name": "permissions",
  "layer": "authorization",
  "purpose": "RBAC permission checking: wildcard/exact/prefix matching policies, FastAPI dependency factories (require, require_all, require_any), principal resolution from request state, structured audit logging hook, and permission-string validation.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Principal objects exposing a `permissions` iterable; permission strings in 'namespace:action' form.",
  "outputs": "Booleans / missing-permission lists; FastAPI dependencies that raise HTTP 403 on denial.",
  "files_created": [],
  "security_notes": "Deny-by-default: require_all/require_any raise 403 when the principal is missing or lacks permissions. Wildcard policy grants 'ns:*' and '*'; switch to 'exact' via configure_permission_policy for stricter matching. Audit hook logs principal permission counts and outcomes but never logs credential material. Wire a real principal resolver before production use; the placeholder raises rather than silently allowing.",
  "ai_usage": "Import what you need from `scrapyard.authorization.permissions`; set the principal resolver (set_principal_resolver or request.state.principal), then guard routes with require()/require_all()/require_any().",
  "example": "from scrapyard.authorization.permissions import require_all; app.get('/x', dependencies=[Depends(require_all(['billing:read']))])",
  "import_path": "scrapyard.authorization.permissions"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import re
from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Protocol,
)

import fastapi
from fastapi import Depends, HTTPException, status

STATUS = "core"

logger = logging.getLogger("scrapyard.authorization.permissions")

_PERMISSION_RE = re.compile(r"^[A-Za-z0-9_.\-]+:[A-Za-z0-9_.\-]+$|^[A-Za-z0-9_.\-]+:\*$|^\*$")


class HasPermissions(Protocol):
    permissions: Iterable[str]

class PermissionPolicy(Protocol):
    def match(self, permission: str) -> bool:
        ...

class AuditLogger(Protocol):
    def log(self, principal: HasPermissions, required: str, success: bool) -> None:
        ...

class PrincipalResolver(Protocol):
    def resolve(self) -> Optional[HasPermissions]:
        ...

class PermissionNamespaceRegistry(Protocol):
    def register(self, namespace: str) -> None:
        ...

class MissingPermissionHandler(Protocol):
    def handle(self, missing_permissions: List[str]) -> None:
        ...

class PermissionSerializer(Protocol):
    def serialize(self, permission: str) -> str:
        ...

class PermissionFormatError(Exception):
    pass

class PermissionNamespaceError(Exception):
    pass


# --- module configuration (mutable via the configure/set_* functions) ---

_VALID_POLICIES = ("wildcard", "exact", "prefix")
_policy_mode: str = "wildcard"
_principal_resolver: Optional[Callable[[], Optional[HasPermissions]]] = None
_audit_logger: Optional[Callable[[str, str, bool], None]] = None
_permission_serializer: Optional[Callable[[str], str]] = None
_missing_permission_handler: Optional[Callable[[List[str]], None]] = None
_registered_namespaces: set[str] = set()


def configure_permission_policy(policy: str = "wildcard") -> None:
    """Set the active matching policy: 'wildcard' (default), 'exact', or 'prefix'.

    - wildcard: 'ns:*' grants everything under ns; '*' grants all.
    - exact: only literal string equality grants.
    - prefix: a granted permission that is a prefix of the required one grants
      (e.g. granted 'billing' matches required 'billing:read').
    """
    global _policy_mode
    if policy not in _VALID_POLICIES:
        raise ValueError(f"Invalid permission policy {policy!r}; expected one of {_VALID_POLICIES}")
    _policy_mode = policy


def get_permission_policy() -> str:
    """Return the currently configured matching policy."""
    return _policy_mode


def has_permission(principal: HasPermissions, required: str) -> bool:
    """Policy-aware check. Under 'wildcard': 'billing:*' grants 'billing:read'; '*' grants all."""
    perms = set(getattr(principal, "permissions", []) or [])
    if required in perms:
        return True
    if _policy_mode == "exact":
        return False
    if _policy_mode == "prefix":
        return any(required.startswith(granted) for granted in perms if granted)
    # wildcard (default)
    if "*" in perms:
        return True
    namespace = required.split(":", 1)[0]
    return (namespace + ":*") in perms


def check_permissions(principal: HasPermissions, required: List[str]) -> List[str]:
    """Returns list of missing permissions; honours the configured matching policy."""
    return [perm for perm in required if not has_permission(principal, perm)]


def require_all(permissions: List[str]):
    """FastAPI dependency factory: principal must hold ALL listed permissions or 403."""
    def _checker(principal=Depends(get_principal_from_request)):  # noqa: ANN001
        if principal is None:
            _handle_missing(list(permissions))
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permissions denied")
        missing = check_permissions(principal, permissions)
        for perm in permissions:
            audit_permission_check(principal, perm, perm not in missing)
        if missing:
            _handle_missing(missing)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permissions denied")
        return principal

    return _checker


def require_any(permissions: List[str]):
    """FastAPI dependency factory: principal must hold AT LEAST ONE listed permission or 403."""
    def _checker(principal=Depends(get_principal_from_request)):  # noqa: ANN001
        if principal is None:
            _handle_missing(list(permissions))
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permissions denied")
        granted = any(has_permission(principal, perm) for perm in permissions)
        audit_permission_check(principal, "|".join(permissions), granted)
        if not granted:
            _handle_missing(list(permissions))
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permissions denied")
        return principal

    return _checker


def audit_permission_check(principal: HasPermissions, required: str, success: bool) -> None:
    """Structured-log hook fired after every permission decision.

    Emits an INFO (grant) / WARNING (deny) record with stable extra fields, then
    invokes any custom audit logger registered via set_audit_logger.
    """
    principal_id = getattr(principal, "id", None) or getattr(principal, "sub", None) or repr(type(principal).__name__)
    record = {
        "event": "permission_check",
        "principal": str(principal_id),
        "required": required,
        "granted": success,
        "policy": _policy_mode,
    }
    logger.log(
        logging.INFO if success else logging.WARNING,
        "permission_check principal=%s required=%s granted=%s policy=%s",
        record["principal"], required, success, _policy_mode,
        extra={"audit": record},
    )
    if _audit_logger is not None:
        _audit_logger(str(principal_id), required, success)


def get_principal_from_request(request: fastapi.Request) -> Optional[HasPermissions]:
    """Extract principal: custom resolver (set_principal_resolver) wins, else request.state.principal."""
    if _principal_resolver is not None:
        return _principal_resolver()
    return request.state.principal if hasattr(request.state, "principal") else None


def bulk_has_permissions(principal: HasPermissions, required: List[str]) -> Dict[str, bool]:
    """Bulk check for multiple permissions; each result honours the configured policy."""
    return {perm: has_permission(principal, perm) for perm in required}


def serialize_permissions(principal: HasPermissions) -> List[str]:
    """Serialize permissions for logging/API responses via the registered serializer (identity by default)."""
    perms = list(getattr(principal, "permissions", []) or [])
    if _permission_serializer is not None:
        return [_permission_serializer(p) for p in perms]
    return perms


def set_principal_resolver(resolver: Callable[[], Optional[HasPermissions]]) -> None:
    """Register a zero-arg callable returning the current principal (overrides request.state lookup)."""
    global _principal_resolver
    if resolver is not None and not callable(resolver):
        raise TypeError("resolver must be callable or None")
    _principal_resolver = resolver


def add_permission_namespace(namespace: str) -> None:
    """Register a permission namespace; validate_permission then rejects unknown namespaces."""
    if not namespace or not re.match(r"^[A-Za-z0-9_.\-]+$", namespace):
        raise PermissionNamespaceError(f"Invalid namespace: {namespace!r}")
    _registered_namespaces.add(namespace)


def get_registered_namespaces() -> List[str]:
    """Return the sorted list of registered namespaces (empty = namespace checking disabled)."""
    return sorted(_registered_namespaces)


def validate_permission(permission: str) -> bool:
    """Validate 'namespace:action' format. Raises PermissionFormatError when malformed.

    If namespaces have been registered via add_permission_namespace, the
    namespace must be one of them (except the global '*').
    """
    if not isinstance(permission, str) or ":" not in permission and permission != "*":
        raise PermissionFormatError(f"Invalid permission format: {permission!r}")
    if not _PERMISSION_RE.match(permission):
        raise PermissionFormatError(f"Invalid permission format: {permission!r}")
    if permission != "*" and _registered_namespaces:
        namespace = permission.split(":", 1)[0]
        if namespace not in _registered_namespaces:
            return False
    return True


def get_missing_permissions(principal: HasPermissions, required: List[str]) -> List[str]:
    """Returns required permissions not granted to the principal (policy-aware)."""
    return check_permissions(principal, required)


def set_audit_logger(audit_logger: Callable[[str, str, bool], None]) -> None:
    """Register a callable(principal_id, required, granted) invoked on every audit event."""
    global _audit_logger
    if audit_logger is not None and not callable(audit_logger):
        raise TypeError("audit_logger must be callable or None")
    _audit_logger = audit_logger


def set_permission_serializer(serializer: Callable[[str], str]) -> None:
    """Register a per-permission serializer used by serialize_permissions."""
    global _permission_serializer
    if serializer is not None and not callable(serializer):
        raise TypeError("serializer must be callable or None")
    _permission_serializer = serializer


def set_missing_permission_handler(handler: Callable[[List[str]], None]) -> None:
    """Register a callable invoked with the missing-permission list just before a 403 is raised."""
    global _missing_permission_handler
    if handler is not None and not callable(handler):
        raise TypeError("handler must be callable or None")
    _missing_permission_handler = handler


def _handle_missing(missing: List[str]) -> None:
    if _missing_permission_handler is not None:
        try:
            _missing_permission_handler(missing)
        except Exception:  # handler must never break the 403 path
            logger.exception("missing-permission handler raised")


# --- grafted from original part (API stability) ---
def require(permission: str):
    """FastAPI dependency factory. Override _current_principal_placeholder in
    your app: app.dependency_overrides[_current_principal_placeholder] = get_user."""
    def _checker(principal=Depends(_current_principal_placeholder)):  # noqa: ANN001
        if not has_permission(principal, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission denied")
        return principal

    return _checker


def _current_principal_placeholder():
    raise RuntimeError("wire get_current_principal via dependency_overrides")


def _selftest() -> None:
    from types import SimpleNamespace

    # reset module state
    configure_permission_policy("wildcard")
    set_principal_resolver(None)  # type: ignore[arg-type]
    set_audit_logger(None)  # type: ignore[arg-type]
    set_permission_serializer(None)  # type: ignore[arg-type]
    set_missing_permission_handler(None)  # type: ignore[arg-type]

    alice = SimpleNamespace(id="alice", permissions=["billing:read", "reports:*"])
    admin = SimpleNamespace(id="root", permissions=["*"])
    nobody = SimpleNamespace(id="nobody", permissions=[])

    # wildcard policy
    assert has_permission(alice, "billing:read")
    assert not has_permission(alice, "billing:write")
    assert has_permission(alice, "reports:export")
    assert has_permission(admin, "anything:at_all")
    assert check_permissions(alice, ["billing:read", "billing:write"]) == ["billing:write"]
    assert bulk_has_permissions(alice, ["billing:read", "reports:export"]) == {
        "billing:read": True, "reports:export": True}

    # exact policy
    configure_permission_policy("exact")
    assert not has_permission(alice, "reports:export")
    assert not has_permission(admin, "anything:at_all")
    assert has_permission(alice, "billing:read")

    # prefix policy
    configure_permission_policy("prefix")
    bob = SimpleNamespace(id="bob", permissions=["billing"])
    assert has_permission(bob, "billing:read")
    assert not has_permission(bob, "reports:read")
    configure_permission_policy("wildcard")
    try:
        configure_permission_policy("nonsense")
        raise AssertionError("invalid policy accepted")
    except ValueError:
        pass

    # require_all fail-closed: missing permission -> 403
    checker = require_all(["billing:read", "billing:write"])
    try:
        checker(principal=alice)
        raise AssertionError("require_all let a missing permission through")
    except HTTPException as e:
        assert e.status_code == 403
    # and with NO principal at all -> 403 (fail closed, not fail open)
    try:
        checker(principal=None)
        raise AssertionError("require_all passed with no principal")
    except HTTPException as e:
        assert e.status_code == 403
    # all present -> principal returned
    assert checker(principal=admin) is admin

    # require_any
    any_checker = require_any(["billing:write", "billing:read"])
    assert any_checker(principal=alice) is alice
    try:
        any_checker(principal=nobody)
        raise AssertionError("require_any passed with no grants")
    except HTTPException as e:
        assert e.status_code == 403

    # audit hook fires with structured outcome
    events: list[tuple[str, str, bool]] = []
    set_audit_logger(lambda pid, req, ok: events.append((pid, req, ok)))
    audit_permission_check(alice, "billing:read", True)
    assert events == [("alice", "billing:read", True)]
    set_audit_logger(None)  # type: ignore[arg-type]

    # missing-permission handler observes the denial
    seen: list[List[str]] = []
    set_missing_permission_handler(lambda missing: seen.append(missing))
    try:
        require_all(["ops:deploy"])(principal=nobody)
    except HTTPException:
        pass
    assert seen and seen[-1] == ["ops:deploy"]
    set_missing_permission_handler(None)  # type: ignore[arg-type]

    # validation + namespaces
    assert validate_permission("billing:read") is True
    assert validate_permission("reports:*") is True
    assert validate_permission("*") is True
    for bad in ("no_colon", "", "a:b:c!!"):
        try:
            validate_permission(bad)
            raise AssertionError(f"accepted malformed permission {bad!r}")
        except PermissionFormatError:
            pass
    add_permission_namespace("billing")
    assert validate_permission("billing:read") is True
    assert validate_permission("unknown:read") is False
    _registered_namespaces.clear()

    # serializer hook
    set_permission_serializer(str.upper)
    assert serialize_permissions(alice) == ["BILLING:READ", "REPORTS:*"]
    set_permission_serializer(None)  # type: ignore[arg-type]

    # principal resolver override
    set_principal_resolver(lambda: admin)
    assert get_principal_from_request(request=None) is admin  # type: ignore[arg-type]
    set_principal_resolver(None)  # type: ignore[arg-type]

    print("permissions selftest: PASS")


if __name__ == "__main__":
    _selftest()
