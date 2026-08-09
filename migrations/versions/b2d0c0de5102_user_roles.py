"""user_roles — persistent role assignments for role-based authorization

Revision ID: b2d0c0de5102
Revises: a1c0ffee5101
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "b2d0c0de5102"
down_revision = "a1c0ffee5101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "role", name="uq_user_role"),
    )
    op.create_index(op.f("ix_user_roles_user_id"), "user_roles", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_roles_role"), "user_roles", ["role"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_roles_role"), table_name="user_roles")
    op.drop_index(op.f("ix_user_roles_user_id"), table_name="user_roles")
    op.drop_table("user_roles")
