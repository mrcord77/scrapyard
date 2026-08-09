"""
tenant_access — Authorize a principal against a tenant boundary.

### PART-META-JSON
{
  "name": "tenant_access",
  "layer": "authorization",
  "purpose": "Authorize a principal against a tenant boundary.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: authorize_principal(principal, resource, policy, audit); TenantAwareQuery(query, tenant_id); bulk_tenant_check(principals, resource_tenant_id); audit_tenant_access(principal, resource, success, metadata); TenantAccessError(Exception); Principal(...); Resource(...); Policy(...) (plus more).",
  "outputs": "Returns: authorize_principal -> None; TenantAwareQuery -> Query; bulk_tenant_check -> List[bool]; audit_tenant_access -> None; same_tenant -> bool.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `authorize_principal` from `scrapyard.authorization.tenant_access` and call it as shown in `example`; run `py -m scrapyard.authorization.tenant_access` to see its offline selftest.",
  "example": "from scrapyard.authorization.tenant_access import authorize_principal",
  "import_path": "scrapyard.authorization.tenant_access"
}
### END-PART-META
"""
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, Query
from sqlalchemy import select
from typing import List, Optional, TypeVar, Generic, Any, Dict

T = TypeVar('T')

class Principal(BaseModel):
    id: str
    tenant_id: str

class Resource(BaseModel):
    id: str
    tenant_id: Optional[str] = None

class Policy(BaseModel):
    rules: List[Dict[str, Any]]
    fallback: str = "deny"

class AuditContext(BaseModel):
    user_id: str
    resource_id: str

class Rule(BaseModel):
    condition: str
    action: str

class TenantPolicy(Generic[T]):
    def __init__(self, rules: List[Rule], fallback: str = "deny"):
        self.rules = rules
        self.fallback = fallback

def authorize_principal(principal: Principal, resource: Resource, policy: Optional[Policy] = None, audit: Optional[AuditContext] = None) -> None:
    if not same_tenant(principal.tenant_id, resource.tenant_id):
        raise HTTPException(403, "cross-tenant access denied")
    
    if policy is not None and principal.tenant_id != resource.tenant_id:
        from sqlalchemy import or_
        query = select(Rule).where(or_(*[Rule.condition == f"principal.tenant_id == '{principal.tenant_id}'"] + [Rule.condition == f"resource.tenant_id == '{resource.tenant_id}'"]))
        with Session() as session:
            rules = session.execute(query).scalars().all()
        
        if not any(rule.action == "allow" for rule in rules):
            raise HTTPException(403, "policy denied")
    
    if audit is not None:
        audit_tenant_access(principal, resource, True)

class TenantFilter(Generic[T]):
    def __init__(self, tenant_id: str, page: int = 1, per_page: int = 20):
        self.tenant_id = tenant_id
        self.page = page
        self.per_page = per_page

def TenantAwareQuery(query: Query, tenant_id: str) -> Query:
    return query.filter(Resource.tenant_id == tenant_id)

def bulk_tenant_check(principals: List[Principal], resource_tenant_id: str) -> List[bool]:
    results = []
    for principal in principals:
        if same_tenant(principal.tenant_id, resource_tenant_id):
            results.append(True)
        else:
            try:
                from sqlalchemy import or_
                with Session() as session:
                    query = select(Principal).where(or_(*[Principal.tenant_id == p.tenant_id for p in principals]))
                    if not session.execute(query).scalars().all():
                        raise HTTPException(403, "cross-tenant access denied")
                    results.append(True)
            except:
                results.append(False)
    return results

class TenantSerializer(BaseModel):
    def __init__(self, data: Any, policy: Optional[Policy] = None):
        self.data = data
        self.policy = policy
    
    def serialize(self) -> dict:
        serialized_data = {}
        for key, value in self.data.items():
            if isinstance(value, Principal):
                serialized_data[key] = {"id": value.id, "tenant_id": value.tenant_id}
            else:
                serialized_data[key] = value
        return serialized_data

def audit_tenant_access(principal: Principal, resource: Resource, success: bool, metadata: Optional[Dict[str, Any]] = None) -> None:
    if metadata is None:
        metadata = {}
    metadata["principal_id"] = principal.id
    metadata["resource_id"] = resource.id
    metadata["success"] = success
    
    from scrapyard.logging import log_audit_event
    log_audit_event(metadata)

class TenantPolicyLoader:
    def __init__(self, policy_id: str, env: str = "prod"):
        self.policy_id = policy_id
        self.env = env

class TenantAccessError(Exception):
    pass

class TenantAccessConfig(BaseModel):
    default_policy: str = "deny"
    audit_enabled: bool = True

def same_tenant(principal_tenant_id, resource_tenant_id) -> bool:
    return principal_tenant_id is not None and principal_tenant_id == resource_tenant_id


# --- grafted from original part (API stability) ---
def require_tenant(principal_tenant_id, resource_tenant_id) -> None:
    if not same_tenant(principal_tenant_id, resource_tenant_id):
        from fastapi import HTTPException
        raise HTTPException(403, "cross-tenant access denied")


def _selftest() -> None:
    assert same_tenant("t1", "t1") is True
    assert same_tenant("t1", "t2") is False               # negative: cross-tenant
    assert same_tenant(None, None) is False               # negative: null fails closed

    require_tenant("t1", "t1")                             # allowed: no raise
    try:                                                  # denied: 403
        require_tenant("t1", "t2")
        raise AssertionError("require_tenant allowed cross-tenant access")
    except HTTPException as e:
        assert e.status_code == 403

    p = Principal(id="u1", tenant_id="t1")
    authorize_principal(p, Resource(id="r1", tenant_id="t1"))   # same tenant -> ok
    try:                                                  # cross-tenant resource -> 403
        authorize_principal(p, Resource(id="r2", tenant_id="t2"))
        raise AssertionError("authorize_principal allowed cross-tenant access")
    except HTTPException as e:
        assert e.status_code == 403
    print("tenant_access selftest: PASS")


if __name__ == "__main__":
    _selftest()

