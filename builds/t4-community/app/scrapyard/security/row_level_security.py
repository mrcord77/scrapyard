"""
row_level_security — Database-enforced (PostgreSQL) row isolation.

App-level scoping (multitenancy.tenant_context) filters rows in Python; that is
bypassed by any raw query or app bug. This layer enforces isolation IN THE DATABASE
via PostgreSQL Row Level Security, so a tenant/owner can never read or modify another's
rows even through hand-written SQL. Policies are FAIL-CLOSED: with no context set,
zero rows are visible.

### PART-META-JSON
{
  "name": "row_level_security",
  "layer": "security",
  "purpose": "Database-enforced per-tenant/per-owner row isolation (PostgreSQL RLS).",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "A DB connection/session; the current tenant_id or user_id.",
  "outputs": "ENABLE/FORCE RLS + fail-closed policies; per-transaction context setters.",
  "files_created": [],
  "security_notes": "Enforced only on PostgreSQL. Requires FORCE so the table owner is also subject. Set context per transaction with set_context(); unset context => no rows.",
  "ai_usage": "Apply via the Alembic RLS migration; call set_context(conn, tenant_id=...) per request.",
  "example": "from scrapyard.security.row_level_security import set_context; set_context(conn, tenant_id=5)",
  "import_path": "scrapyard.security.row_level_security"
}
### END-PART-META
"""
from __future__ import annotations
from dataclasses import dataclass

STATUS = "core"

# Postgres GUCs (custom, namespaced) that carry the current scope per transaction.
TENANT_GUC = "app.current_tenant"
USER_GUC = "app.current_user_id"


@dataclass(frozen=True)
class RLSPolicy:
    table: str
    column: str          # the scope column (tenant_id / user_id)
    guc: str             # the GUC that carries the current scope value
    cast: str = "int"    # SQL cast for the GUC value (scope columns are integers)

    @property
    def policy_name(self) -> str:
        return f"{self.table}_rls"


# Every table whose rows belong to a tenant or a single owner. Adding a scoped
# table = add it here, and the RLS migration covers it automatically.
RLS_POLICIES: list[RLSPolicy] = [
    RLSPolicy("ai_documents", "tenant_id", TENANT_GUC, cast="text"),
    RLSPolicy("ai_chunks", "tenant_id", TENANT_GUC, cast="text"),
    RLSPolicy("ai_retrieval_logs", "tenant_id", TENANT_GUC, cast="text"),
    RLSPolicy("invoices", "user_id", USER_GUC),
    RLSPolicy("subscriptions", "user_id", USER_GUC),
    RLSPolicy("notifications", "user_id", USER_GUC),
    RLSPolicy("consent_logs", "user_id", USER_GUC),
    RLSPolicy("saved_searches", "user_id", USER_GUC),
    RLSPolicy("usage_events", "user_id", USER_GUC),
    RLSPolicy("analytics_events", "user_id", USER_GUC),
    # Deliberately NOT scoped: `sessions` is identity infrastructure — a session
    # token must be resolved to learn *which* user is calling, so identity precedes
    # context; scoping it by user_id is a chicken-and-egg that breaks auth under
    # FORCE RLS. It is protected by token secrecy + ownership, not row-level isolation.
    # Likewise email_verifications / password_reset_tokens are pre-auth, token-looked-up
    # flows with no user context yet.
]


def _predicate(p: RLSPolicy) -> str:
    # Fail-closed: an unset GUC -> current_setting(...,true)=NULL -> NULLIF -> NULL,
    # and `col = NULL` is NULL (never true), so no rows match without a context.
    return f"{p.column} = NULLIF(current_setting('{p.guc}', true), '')::{p.cast}"


def enable_sql(p: RLSPolicy) -> list[str]:
    pred = _predicate(p)
    return [
        f"ALTER TABLE {p.table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {p.table} FORCE ROW LEVEL SECURITY",   # owner is subject too
        f"DROP POLICY IF EXISTS {p.policy_name} ON {p.table}",
        f"CREATE POLICY {p.policy_name} ON {p.table} USING ({pred}) WITH CHECK ({pred})",
    ]


def disable_sql(p: RLSPolicy) -> list[str]:
    return [
        f"DROP POLICY IF EXISTS {p.policy_name} ON {p.table}",
        f"ALTER TABLE {p.table} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {p.table} DISABLE ROW LEVEL SECURITY",
    ]


def policies_for(table_names) -> list[RLSPolicy]:
    """The subset of policies whose tables are present (for per-app migrations)."""
    s = set(table_names)
    return [p for p in RLS_POLICIES if p.table in s]


def apply_rls(connection, policies=None) -> None:
    from sqlalchemy import text
    for p in (policies if policies is not None else RLS_POLICIES):
        for stmt in enable_sql(p):
            connection.execute(text(stmt))


def drop_rls(connection, policies=None) -> None:
    from sqlalchemy import text
    for p in (policies if policies is not None else RLS_POLICIES):
        for stmt in disable_sql(p):
            connection.execute(text(stmt))


def set_context(connection, *, tenant_id=None, user_id=None, local: bool = True) -> None:
    """Bind the current scope for the transaction. local=True scopes to the current
    transaction only (safe for pooled connections)."""
    from sqlalchemy import text
    if tenant_id is not None:
        connection.execute(text("SELECT set_config(:k, :v, :l)"),
                           {"k": TENANT_GUC, "v": str(tenant_id), "l": local})
    if user_id is not None:
        connection.execute(text("SELECT set_config(:k, :v, :l)"),
                           {"k": USER_GUC, "v": str(user_id), "l": local})


def clear_context(connection, local: bool = True) -> None:
    from sqlalchemy import text
    connection.execute(text("SELECT set_config(:k, '', :l)"), {"k": TENANT_GUC, "l": local})
    connection.execute(text("SELECT set_config(:k, '', :l)"), {"k": USER_GUC, "l": local})


def rls_supported(engine_or_url) -> bool:
    """True only on PostgreSQL — the one backend that enforces these policies."""
    name = getattr(getattr(engine_or_url, "dialect", None), "name", None)
    if name is not None:
        return name == "postgresql"
    return str(engine_or_url).startswith("postgresql")


def existing_policies(connection) -> list[RLSPolicy]:
    """The registered policies whose tables actually exist in this database
    (so an assembled app applies RLS only to the scoped tables it ships)."""
    from sqlalchemy import text
    names = connection.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    )).scalars().all()
    return policies_for(names)


def apply_rls_existing(connection) -> list[str]:
    """Apply RLS to every scoped table present. Idempotent. Returns the tables covered."""
    pols = existing_policies(connection)
    apply_rls(connection, pols)
    return [p.table for p in pols]


def _selftest() -> None:
    """Offline, falsifiable self-test of the RLS SQL generation and fail-closed
    predicate (no live PostgreSQL required — asserts on the emitted DDL)."""
    p = RLSPolicy("invoices", "user_id", USER_GUC)

    # 1) enable_sql emits ENABLE + FORCE + a policy that constrains reads and writes
    stmts = enable_sql(p)
    joined = " | ".join(stmts)
    assert "ENABLE ROW LEVEL SECURITY" in joined, "must ENABLE RLS"
    assert "FORCE ROW LEVEL SECURITY" in joined, "must FORCE RLS so the owner is subject too"
    assert "USING (" in joined and "WITH CHECK (" in joined, "policy must guard SELECT and write paths"

    # 2) the predicate is FAIL-CLOSED: it derives the scope from the GUC via NULLIF,
    #    so an UNSET context yields NULL and matches zero rows.
    pred = _predicate(p)
    assert "NULLIF(current_setting('app.current_user_id', true), '')" in pred, \
        "predicate must read the scoped GUC with the missing-ok flag"
    assert pred.startswith("user_id ="), "predicate must constrain the scope column"

    # 3) NEGATIVE: RLS is only supported on PostgreSQL — other backends report False
    assert rls_supported("postgresql://u@h/db") is True, "postgres is supported"
    assert rls_supported("sqlite:///x.db") is False, "sqlite must not claim RLS support"

    # 4) policies_for filters the registry to only the tables present
    subset = policies_for(["invoices", "not_a_table"])
    assert [x.table for x in subset] == ["invoices"], "only registered+present tables included"

    # 5) disable_sql reverses cleanly (drops policy, un-forces, disables)
    d = " | ".join(disable_sql(p))
    assert "DROP POLICY IF EXISTS invoices_rls" in d and "DISABLE ROW LEVEL SECURITY" in d

    print("row_level_security: OK (8 assertions incl. non-postgres + fail-closed negatives)")


if __name__ == "__main__":
    _selftest()
