"""Alembic environment — schema source of truth for Scrapyard apps.

target_metadata is built from the model registry (all table-defining parts), so
autogenerate diffs migrations against the real composed schema. The database URL
comes from $DATABASE_URL (never hardcoded)."""
import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

# allow a subset via $SCRAPYARD_MODEL_MODULES (comma-sep) for generated-app migrations
_only = os.environ.get("SCRAPYARD_MODEL_MODULES")
only = [m.strip() for m in _only.split(",") if m.strip()] if _only else None
from scrapyard.database.metadata import target_metadata as _md
target_metadata = _md(only)

_url = os.environ.get("DATABASE_URL")
if _url:
    config.set_main_option("sqlalchemy.url", _url)


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      target_metadata=target_metadata, literal_binds=True,
                      compare_type=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
