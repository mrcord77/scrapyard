"""
admin_access — Guard admin-only surfaces.

### PART-META-JSON
{
  "name": "admin_access",
  "layer": "authorization",
  "purpose": "Guard admin-only surfaces.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Public API: configure_admin_policy(policy); register_admin_hook(hook); bulk_require_admin(principals); get_admin_principal_info(principal); check_admin_permission(principal, required_permission); AdminPrincipalNotFoundError(...); AdminHookError(...); AdminAccessAudit(...) (plus more).",
  "outputs": "Returns: configure_admin_policy -> None; register_admin_hook -> None; bulk_require_admin -> None; get_admin_principal_info -> dict; check_admin_permission -> bool.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `configure_admin_policy` from `scrapyard.authorization.admin_access` and call it as shown in `example`; run `py -m scrapyard.authorization.admin_access` to see its offline selftest.",
  "example": "from scrapyard.authorization.admin_access import configure_admin_policy",
  "import_path": "scrapyard.authorization.admin_access"
}
### END-PART-META
"""
from __future__ import annotations
from typing import Any, List, Optional, Callable
import logging
from fastapi import HTTPException
from scrapyard.authorization.permissions import has_permission

STATUS = "core"
logger = logging.getLogger(__name__)
_ADMIN_POLICY: Optional[Any] = None

class AdminPrincipalNotFoundError(Exception):
    pass

class AdminHookError(Exception):
    pass

class AdminAccessAudit:
    @staticmethod
    def log_admin_access(principal: Any, action: str, resource: str) -> None:
        """Logs admin access for audit/metrics."""
        logger.info("admin_access principal=%s action=%s resource=%s",
                    getattr(principal, "id", None), action, resource)

def configure_admin_policy(policy: Optional[Any] = None) -> None:
    """Sets a global admin policy for the module."""
    global _ADMIN_POLICY
    if policy is not None and not callable(policy) and not hasattr(policy, "required_permission"):
        raise TypeError("admin policy must be callable or define required_permission")
    _ADMIN_POLICY = policy

def register_admin_hook(hook: Callable[[Any, str], None]) -> None:
    """Registers a hook to be called on admin actions."""
    AdminAccessAudit.log_admin_access = hook

def bulk_require_admin(principals: List[Any]) -> None:
    """Validates a list of principals for admin access, raising 403 if any fail."""
    for principal in principals:
        require_admin(principal)

def get_admin_principal_info(principal: Any) -> dict:
    """Returns structured admin principal info (e.g., roles, scopes, permissions)."""
    if principal is None:
        raise AdminPrincipalNotFoundError("Principal is required")
    return {
        "id": getattr(principal, "id", None),
        "roles": list(getattr(principal, "roles", []) or []),
        "permissions": get_admin_permissions(principal),
        "is_admin": is_admin(principal),
    }

def check_admin_permission(principal: Any, required_permission: str) -> bool:
    """Returns whether the principal has a specific admin-level permission."""
    return has_permission(principal, required_permission)

def require_admin_with_policy(principal: Any, policy: Any) -> None:
    """Enforces admin access with configurable policy (e.g., role-based, scope-based, or time-based)."""
    if not check_admin_permission(principal, policy.required_permission):
        raise AdminPrincipalNotFoundError("Principal lacks required permission")

def is_admin_with_scope(principal: Any, scope: str) -> bool:
    """Returns whether the principal is an admin with a specific scope."""
    return has_permission(principal, f"{scope}:admin")

def get_admin_permissions(principal: Any) -> List[str]:
    """Returns a list of admin permissions the principal has."""
    return sorted(set(getattr(principal, "permissions", []) or []))

def require_admin_or_raise(principal: Any, message: str = "Admin access required") -> None:
    """Custom message support for 403 exceptions."""
    if not check_admin_permission(principal, "*"):
        raise HTTPException(status_code=403, detail=message)

def audit_admin_access(principal: Any, action: str, resource: str) -> None:
    """Logs admin access for audit/metrics, with optional hooks for custom logging systems."""
    try:
        AdminAccessAudit.log_admin_access(principal, action, resource)
    except Exception as e:
        raise AdminHookError("Failed to log admin access") from e

def is_admin(principal: Any) -> bool:
    """Returns whether the principal has admin/owner authority."""
    if callable(_ADMIN_POLICY):
        return bool(_ADMIN_POLICY(principal))
    if _ADMIN_POLICY is not None:
        return check_admin_permission(principal, _ADMIN_POLICY.required_permission)
    return check_admin_permission(principal, "users:read") or check_admin_permission(principal, "*")

def require_admin(principal: Any) -> None:
    """Raise 403 unless the principal has admin/owner authority."""
    if not is_admin(principal):
        raise HTTPException(status_code=403, detail="admin access required")


def _selftest() -> None:
    from types import SimpleNamespace
    from scrapyard.authorization.permissions import configure_permission_policy

    configure_permission_policy("wildcard")
    superadmin = SimpleNamespace(id="root", permissions=["*"])
    reader = SimpleNamespace(id="ops", permissions=["users:read"])
    guest = SimpleNamespace(id="guest", permissions=["content:read"])

    assert is_admin(superadmin) is True                   # wildcard confers admin
    assert is_admin(reader) is True                       # users:read is admin-authority here
    assert is_admin(guest) is False                       # negative: not an admin
    assert check_admin_permission(superadmin, "billing:write") is True
    assert check_admin_permission(guest, "billing:write") is False
    assert get_admin_principal_info(superadmin)["permissions"] == ["*"]

    configure_admin_policy(lambda principal: getattr(principal, "id", "") == "ops")
    assert is_admin(reader) and not is_admin(superadmin)
    configure_admin_policy(None)

    require_admin(superadmin)                              # allowed path: no raise
    try:                                                  # denied path: fail closed 403
        require_admin(guest)
        raise AssertionError("require_admin let a non-admin through")
    except HTTPException as e:
        assert e.status_code == 403
    try:
        require_admin_or_raise(guest, "nope")
        raise AssertionError("require_admin_or_raise let a non-admin through")
    except HTTPException as e:
        assert e.status_code == 403 and e.detail == "nope"
    print("admin_access selftest: PASS")


if __name__ == "__main__":
    _selftest()
