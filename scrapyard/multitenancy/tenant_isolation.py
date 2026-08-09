"""
tenant_isolation — Scope queries to the active tenant.

### PART-META-JSON
{
  "name": "tenant_isolation",
  "layer": "multitenancy",
  "purpose": "Tenant isolation that actually isolates: request middleware extracts the tenant (X-Tenant-ID header, subdomain, or token claim - configurable), binds it to the tenant contextvar for the request, and query helpers scope every ORM query to that tenant, fail-closed.",
  "addition": true,
  "status": "core",
  "dependencies": ["fastapi", "sqlalchemy"],
  "inputs": "FastAPI app (middleware), incoming requests, SQLAlchemy queries + tenant-scoped models (tenant_id column), TenantIsolationConfig.",
  "outputs": "Tenant-scoped queries; per-request tenant context; 403 responses for missing tenant under strict policy.",
  "files_created": [],
  "security_notes": "Fail-closed by design: scope_query/apply_tenant_filter raise PermissionError when no tenant is bound, and strict policy 403s requests without a resolvable tenant. Tenant ids come from client-controlled surfaces (header/subdomain) - pair with authentication that proves membership in that tenant; the extractor alone is identification, not authorization. Audit logging records tenant ids only, never row data.",
  "ai_usage": "tenant_isolation_middleware(app) once at startup; configure_tenant_isolation(TenantIsolationConfig(sources=['header','subdomain'])); in data access use scope_query(select(Model), Model).",
  "example": "from scrapyard.multitenancy.tenant_isolation import tenant_isolation_middleware, scope_query",
  "import_path": "scrapyard.multitenancy.tenant_isolation"
}
### END-PART-META
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional, Type

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Mapped, Query, declarative_base, mapped_column

from scrapyard.multitenancy.tenant_context import current_tenant, set_tenant

Base = declarative_base()
log = logging.getLogger("scrapyard.multitenancy.tenant_isolation")

STATUS = "core"


class TenantIsolationError(Exception):
    """Custom exception for tenant isolation violations."""
    pass


class TenantIsolationConfig(BaseModel):
    default_policy: str = "strict"          # strict | soft
    audit_log_level: int = 30
    sources: List[str] = Field(default_factory=lambda: ["header", "subdomain", "token"])
    header_name: str = "X-Tenant-ID"
    base_domain: Optional[str] = None       # e.g. "example.com" for acme.example.com
    token_claim: str = "tenant_id"
    token_decoder: Optional[Callable[[str], dict]] = None  # bearer token -> claims dict
    exempt_paths: List[str] = Field(default_factory=lambda: ["/healthz", "/docs",
                                                             "/openapi.json"])

    model_config = {"arbitrary_types_allowed": True}


_config = TenantIsolationConfig()
_audit_enabled = False


def configure_tenant_isolation(config: Optional[TenantIsolationConfig] = None) -> TenantIsolationConfig:
    """Install a new isolation config (returns the active one)."""
    global _config
    if config is not None:
        if config.default_policy not in ("strict", "soft"):
            raise ValueError(f"unknown policy {config.default_policy!r}")
        _config = config
    return _config


def configure_tenant_policy(policy: str = "strict") -> None:
    """Set the isolation policy. strict = requests without a tenant are rejected;
    soft = requests pass through with no tenant bound (queries still fail closed)."""
    if policy not in ("strict", "soft"):
        raise ValueError(f"unknown policy {policy!r}; valid: strict, soft")
    _config.default_policy = policy


def enable_tenant_audit(enabled: bool = False) -> None:
    """Toggle audit logging of tenant-scoped operations (tenant ids only)."""
    global _audit_enabled
    _audit_enabled = enabled


def _audit(action: str, tenant_id, detail: str = "") -> None:
    if _audit_enabled:
        log.log(_config.audit_log_level, "tenant-audit action=%s tenant=%s %s",
                action, tenant_id, detail)


# ---------------------------------------------------------------------------
# Tenant extraction (the previously always-None hole)
# ---------------------------------------------------------------------------

def _from_header(request: Request) -> Optional[str]:
    value = request.headers.get(_config.header_name)
    return value.strip() if value and value.strip() else None


def _from_subdomain(request: Request) -> Optional[str]:
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if not host:
        return None
    if _config.base_domain:
        suffix = "." + _config.base_domain.lower()
        if host.endswith(suffix):
            sub = host[: -len(suffix)]
            return sub or None
        return None
    parts = host.split(".")
    # generic fallback: acme.api.example.com -> acme (never for bare/loopback hosts)
    if len(parts) >= 3 and parts[0] not in ("www", "localhost"):
        return parts[0]
    return None


def _from_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    decoder = _config.token_decoder
    if decoder is None:
        return None  # no trusted decoder configured -> never guess
    try:
        claims = decoder(token)
    except Exception as e:
        raise TenantIsolationError(f"invalid auth token: {e}")
    value = claims.get(_config.token_claim)
    return str(value) if value is not None else None


_EXTRACTORS = {"header": _from_header, "subdomain": _from_subdomain, "token": _from_token}


def get_tenant_id_from_request(request: Request) -> Optional[str]:
    """REAL extraction: tries the configured sources in order
    (header X-Tenant-ID / subdomain / bearer-token claim); first hit wins."""
    for source in _config.sources:
        extractor = _EXTRACTORS.get(source)
        if extractor is None:
            raise ValueError(f"unknown tenant source {source!r}")
        tid = extractor(request)
        if tid is not None:
            return tid
    return None


def set_tenant_id_from_context(tenant_id=None, request: Optional[Request] = None) -> None:
    """Bind a tenant id to the context (fixed: uses set_tenant(); current_tenant
    is a reader function, not the contextvar itself)."""
    if tenant_id is None and request is not None:
        tenant_id = get_tenant_id_from_request(request)
    set_tenant(tenant_id)


def get_tenant_id_from_context():
    return current_tenant()


# ---------------------------------------------------------------------------
# Query scoping (fail-closed)
# ---------------------------------------------------------------------------

class TenantAwareQuery(Query):
    def tenant_filter(self, model: Type[Base], tenant_id=None) -> Query:
        tid = tenant_id if tenant_id is not None else get_tenant_id_from_context()
        if tid is None:
            raise PermissionError("no tenant in context; refusing unscoped query")
        return self.where(model.tenant_id == tid)


def is_tenant_scoped(model: Type[Base]) -> bool:
    """Helper to check if a model is tenant-scoped."""
    return hasattr(model, "tenant_id")


def apply_tenant_filter(query, model: Type[Base], tenant_id=None):
    """Apply tenant scoping with optional explicit override. Fail-closed."""
    if not is_tenant_scoped(model):
        raise ValueError(f"{model.__name__} is not tenant-scoped")
    tid = tenant_id if tenant_id is not None else get_tenant_id_from_context()
    if tid is None:
        raise PermissionError("no tenant in context; refusing unscoped query")
    _audit("query", tid, f"model={model.__name__}")
    return query.where(model.tenant_id == tid)


def bulk_apply_tenant_filter(queries: List, model: Type[Base], tenant_id=None) -> List:
    """Applies tenant scoping to a list of queries."""
    return [apply_tenant_filter(q, model, tenant_id) for q in queries]


def tenant_filter_hook(query, model: Type[Base], tenant_id):
    """Configurable hook to apply additional tenant filtering logic."""
    return query.where(model.tenant_id == tenant_id)


def tenant_isolation_serializer(instance, tenant_id) -> dict:
    """Serialize a tenant-scoped ORM instance, refusing cross-tenant leaks:
    raises TenantIsolationError if the row belongs to another tenant."""
    row_tid = getattr(instance, "tenant_id", None)
    if row_tid is not None and str(row_tid) != str(tenant_id):
        raise TenantIsolationError(
            f"attempt to serialize tenant {row_tid} data in tenant {tenant_id} context")
    data = {}
    mapper = getattr(type(instance), "__mapper__", None)
    if mapper is not None:
        for col in mapper.columns:
            data[col.key] = getattr(instance, col.key)
    else:
        data = {k: v for k, v in vars(instance).items() if not k.startswith("_")}
    _audit("serialize", tenant_id, f"type={type(instance).__name__}")
    return data


# ---------------------------------------------------------------------------
# Middleware: extraction is actually applied per request now
# ---------------------------------------------------------------------------

def tenant_isolation_middleware(app: FastAPI) -> FastAPI:
    @app.middleware("http")
    async def enforce_tenant_isolation(request: Request, call_next):
        if request.url.path in _config.exempt_paths:
            return await call_next(request)
        try:
            tid = get_tenant_id_from_request(request)
        except TenantIsolationError as e:
            return JSONResponse(status_code=403, content={"detail": str(e)})
        if tid is None and _config.default_policy == "strict":
            return JSONResponse(status_code=403,
                                content={"detail": "tenant could not be determined"})
        token = None
        from scrapyard.multitenancy.tenant_context import _current
        token = _current.set(tid)
        _audit("request", tid, f"path={request.url.path}")
        try:
            response = await call_next(request)
            return response
        except TenantIsolationError as e:
            return JSONResponse(status_code=403, content={"detail": str(e)})
        finally:
            _current.reset(token)  # never leak a tenant into the next request

    return app


# --- grafted from original part (API stability) ---
def scope_query(query, model, tenant_id=None):
    """Constrain a query to the current (or given) tenant via the model's
    tenant_id column. Raises if the model isn't tenant-scoped — fail closed."""
    from scrapyard.multitenancy.tenant_context import current_tenant
    tid = tenant_id if tenant_id is not None else current_tenant()
    if not hasattr(model, "tenant_id"):
        raise ValueError(f"{model.__name__} is not tenant-scoped")
    if tid is None:
        raise PermissionError("no tenant in context; refusing unscoped query")
    return query.where(model.tenant_id == tid)


def _selftest() -> bool:
    import os
    import tempfile
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, select, String, Integer
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import IntPKModel
    from scrapyard.multitenancy.tenant_context import tenant_scope

    class Doc(IntPKModel):
        __tablename__ = "tenant_isolation_selftest_docs"
        tenant_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
        title: Mapped[str] = mapped_column(String(120), nullable=False)

    class OpenDoc(IntPKModel):
        __tablename__ = "tenant_isolation_selftest_open"
        title: Mapped[str] = mapped_column(String(120), nullable=False)

    # --- query scoping actually isolates rows ---
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        engine = create_engine(f"sqlite:///{os.path.join(td, 't.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as s:
                s.add_all([Doc(tenant_id="a", title="a1"), Doc(tenant_id="a", title="a2"),
                           Doc(tenant_id="b", title="b1")])
                s.commit()
                with tenant_scope("a"):
                    rows = s.scalars(scope_query(select(Doc), Doc)).all()
                    assert sorted(r.title for r in rows) == ["a1", "a2"]
                    rows = s.scalars(apply_tenant_filter(select(Doc), Doc)).all()
                    assert all(r.tenant_id == "a" for r in rows)
                    # serializer refuses cross-tenant rows
                    b_row = s.scalars(select(Doc).where(Doc.tenant_id == "b")).first()
                    try:
                        tenant_isolation_serializer(b_row, "a")
                        raise AssertionError("cross-tenant serialize allowed")
                    except TenantIsolationError:
                        pass
                    ser = tenant_isolation_serializer(rows[0], "a")
                    assert ser["tenant_id"] == "a" and ser["title"] in ("a1", "a2")
                # fail-closed: no tenant bound
                try:
                    scope_query(select(Doc), Doc)
                    raise AssertionError("unscoped query allowed")
                except PermissionError:
                    pass
                try:
                    apply_tenant_filter(select(Doc), Doc)
                    raise AssertionError("unscoped filter allowed")
                except PermissionError:
                    pass
                # non-tenant model rejected
                try:
                    scope_query(select(OpenDoc), OpenDoc, tenant_id="a")
                    raise AssertionError("non-scoped model accepted")
                except ValueError:
                    pass
        finally:
            engine.dispose()

    assert is_tenant_scoped(Doc) and not is_tenant_scoped(OpenDoc)

    # --- extraction: header / subdomain / token claim ---
    configure_tenant_isolation(TenantIsolationConfig(
        base_domain="example.com",
        token_decoder=lambda tok: {"tenant_id": tok.split("|")[0]},
    ))

    class FakeRequest:
        def __init__(self, headers):
            self.headers = headers

    assert get_tenant_id_from_request(FakeRequest({"X-Tenant-ID": "t1"})) == "t1"
    assert get_tenant_id_from_request(FakeRequest({"host": "acme.example.com"})) == "acme"
    assert get_tenant_id_from_request(
        FakeRequest({"authorization": "Bearer t9|signature"})) == "t9"
    assert get_tenant_id_from_request(FakeRequest({"host": "example.com"})) is None
    try:
        configure_tenant_policy("nonsense")
        raise AssertionError("bad policy accepted")
    except ValueError:
        pass

    # --- middleware applies isolation end-to-end ---
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/whoami")
    def whoami():
        return {"tenant": get_tenant_id_from_context()}

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    tenant_isolation_middleware(app)
    configure_tenant_policy("strict")
    with TestClient(app) as client:
        ok = client.get("/whoami", headers={"X-Tenant-ID": "t42"})
        assert ok.status_code == 200 and ok.json() == {"tenant": "t42"}
        blocked = client.get("/whoami")           # no tenant + strict -> 403
        assert blocked.status_code == 403
        assert client.get("/healthz").status_code == 200  # exempt path
        bad = client.get("/whoami", headers={"authorization": "Bearer "})
        assert bad.status_code == 403             # strict, still no tenant
    configure_tenant_policy("soft")
    with TestClient(app) as client:
        soft = client.get("/whoami")
        assert soft.status_code == 200 and soft.json() == {"tenant": None}
    configure_tenant_policy("strict")

    # audit toggle smoke
    enable_tenant_audit(True)
    _audit("selftest", "a")
    enable_tenant_audit(False)

    print("tenant_isolation selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
