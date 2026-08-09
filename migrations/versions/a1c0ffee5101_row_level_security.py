"""row level security policies

Enables + FORCEs PostgreSQL Row Level Security with fail-closed per-tenant/per-owner
policies for every scoped table. No-op on non-PostgreSQL backends (which cannot
enforce RLS — that case is caught as a forbidden production fallback at boot).

Revision ID: a1c0ffee5101
Revises: 47be01e41830
"""
from alembic import op
import sqlalchemy as sa

revision = "a1c0ffee5101"
down_revision = "47be01e41830"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # RLS is a PostgreSQL feature; nothing to do elsewhere
    from scrapyard.security.row_level_security import RLS_POLICIES, enable_sql
    for p in RLS_POLICIES:
        for stmt in enable_sql(p):
            op.execute(stmt)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from scrapyard.security.row_level_security import RLS_POLICIES, disable_sql
    for p in RLS_POLICIES:
        for stmt in disable_sql(p):
            op.execute(stmt)
