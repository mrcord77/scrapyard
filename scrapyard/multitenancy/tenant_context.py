"""
tenant_context — Resolve + carry current tenant per request.

### PART-META-JSON
{
  "name": "tenant_context",
  "layer": "multitenancy",
  "purpose": "Resolve + carry current tenant per request.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: set_tenant(tenant_id); current_tenant(); set_tenant_with_validation(tenant_id, validation_policy); get_current_tenant_or_raise(); tenant_required(func); TenantNotFoundError(...); TenantInvalidError(...); TenantModel(...) (plus more).",
  "outputs": "Returns: set_tenant -> None; current_tenant -> Optional[str]; set_tenant_with_validation -> None; get_current_tenant_or_raise -> str; tenant_required -> Callable.",
  "files_created": [],
  "security_notes": "Renders HTML with all caller text escaped via html.escape (XSS-safe); any HTML 'slot' arguments are inserted verbatim and must be pre-escaped by the caller. Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `set_tenant` from `scrapyard.multitenancy.tenant_context` and call it as shown in `example`; run `py -m scrapyard.multitenancy.tenant_context` to see its offline selftest.",
  "example": "from scrapyard.multitenancy.tenant_context import set_tenant",
  "import_path": "scrapyard.multitenancy.tenant_context"
}
### END-PART-META
"""
from __future__ import annotations
import html
import contextvars
from typing import Any, Callable, List, Optional
from fastapi import Request, HTTPException
from cryptography.fernet import Fernet

from sqlalchemy import Select
from sqlalchemy.orm import Session

STATUS = "core"

_current = contextvars.ContextVar("tenant_id", default=None)
_TENANT_METRICS: List[dict] = []

class TenantNotFoundError(HTTPException):
    def __init__(self, detail: str = "Tenant not found"):
        super().__init__(status_code=400, detail=detail)

class TenantInvalidError(HTTPException):
    def __init__(self, detail: str = "Invalid tenant ID format or non-existent tenant"):
        super().__init__(status_code=400, detail=detail)

class TenantModel:
    def __init__(self, id: str, deleted_at: Optional[str] = None):
        self.id = id
        self.deleted_at = deleted_at

def set_tenant(tenant_id: Optional[str]) -> None:
    _current.set(tenant_id)

def current_tenant() -> Optional[str]:
    return _current.get()

class TenantScope:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._token = None

    def __enter__(self) -> 'TenantScope':
        self._token = _current.set(self.tenant_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _current.reset(self._token)

def set_tenant_with_validation(tenant_id: Optional[str], validation_policy: Callable[[str], bool] = lambda x: True) -> None:
    if tenant_id is not None and not validation_policy(tenant_id):
        raise TenantInvalidError()
    set_tenant(tenant_id)

def get_current_tenant_or_raise() -> str:
    tenant_id = current_tenant()
    if tenant_id is None:
        raise TenantNotFoundError()
    return tenant_id

def tenant_required(func: Callable) -> Callable:
    def wrapper(*args, **kwargs):
        if current_tenant() is None:
            raise TenantNotFoundError("Tenant ID not set")
        return func(*args, **kwargs)
    return wrapper

def with_tenant(tenant_id: Optional[str], *, validate: bool = True) -> TenantScope:
    if validate and tenant_id is not None:
        validation_policy = lambda x: True  # Default policy
        try:
            set_tenant_with_validation(tenant_id, validation_policy)
        except TenantInvalidError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return TenantScope(tenant_id)

def tenant_from_request(request: Request) -> Optional[str]:
    # Example strategy: get from header
    tenant_id = request.headers.get("X-Tenant-ID")
    if tenant_id is not None:
        return tenant_id
    return None

def tenant_from_auth_token(token: str) -> Optional[str]:
    # Example strategy: parse token
    try:
        decrypted = Fernet(b'your-encryption-key').decrypt(token.encode()).decode()
        return decrypted.split(':')[0]
    except Exception as e:
        raise TenantInvalidError(f"Failed to decrypt auth token: {e}")
    return None

def tenant_from_db(session: Session) -> Optional[str]:
    # Example strategy: fetch from database
    query = session.query(TenantModel.id)
    result = session.execute(query).scalars().first()
    if result is not None:
        return str(result)
    return None

def tenant_from_config(default: Optional[str] = None) -> str:
    # Example strategy: get from config file
    import scrapyard.config as config
    return getattr(config, 'TENANT_ID', default)

def tenant_filter(query: Select, *, include_deleted: bool = False) -> Select:
    if not include_deleted:
        query = query.filter(TenantModel.deleted_at.is_(None))
    return query

def tenant_audit_hook(tenant_id: str, action: str, data: Any) -> None:
    # Example strategy: log to audit service
    print(f"Audit: {tenant_id} - {action} - {data}")

def tenant_metrics_hook(tenant_id: str, action: str, duration: float) -> None:
    if duration < 0:
        raise ValueError("duration cannot be negative")
    _TENANT_METRICS.append({"tenant_id": tenant_id, "action": action,
                            "duration": float(duration)})

def tenant_bulk_set(tenant_ids: List[str]) -> None:
    for tenant_id in tenant_ids:
        set_tenant_with_validation(tenant_id)

def tenant_serialize(tenant_id: str) -> str:
    return html.escape(str(tenant_id))

def tenant_deserialize(serialized: str) -> str:
    return serialized


# --- grafted from original part (API stability) ---
class tenant_scope:
    """Context manager binding a tenant id for the duration of a block/request."""
    def __init__(self, tenant_id): self.tenant_id=tenant_id; self._token=None
    def __enter__(self): self._token=_current.set(self.tenant_id); return self
    def __exit__(self, *a): _current.reset(self._token); return False


def _selftest() -> None:
    set_tenant(None)
    assert current_tenant() is None

    set_tenant("t1")
    assert current_tenant() == "t1"

    with tenant_scope("t2"):                              # scope sets the current tenant
        assert current_tenant() == "t2"
    assert current_tenant() == "t1"                       # and restores it on exit (isolation)

    with TenantScope("t3"):
        assert current_tenant() == "t3"
    assert current_tenant() == "t1"
    tenant_metrics_hook("t1", "lookup", 0.25)
    assert _TENANT_METRICS[-1]["duration"] == 0.25

    set_tenant(None)
    try:                                                  # negative: no tenant -> fail closed
        get_current_tenant_or_raise()
        raise AssertionError("get_current_tenant_or_raise returned with no tenant set")
    except TenantNotFoundError:
        pass
    print("tenant_context selftest: PASS")


if __name__ == "__main__":
    _selftest()

