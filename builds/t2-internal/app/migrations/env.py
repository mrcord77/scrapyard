import os
from alembic import context
from sqlalchemy import engine_from_config, pool
config = context.config
_only = os.environ.get('SCRAPYARD_MODEL_MODULES', 'scrapyard.identity.users,scrapyard.identity.session_manager,scrapyard.admin.audit_logs')
only = [m.strip() for m in _only.split(',') if m.strip()] or None
from scrapyard.database.metadata import target_metadata as _md
target_metadata = _md(only)
_url = os.environ.get('DATABASE_URL')
if _url: config.set_main_option('sqlalchemy.url', _url)
def run_online():
    cfg = config.get_section(config.config_ini_section) or {}
    cfg['sqlalchemy.url'] = config.get_main_option('sqlalchemy.url')
    eng = engine_from_config(cfg, prefix='sqlalchemy.', poolclass=pool.NullPool)
    with eng.connect() as c:
        context.configure(connection=c, target_metadata=target_metadata, compare_type=True, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
def run_offline():
    context.configure(url=config.get_main_option('sqlalchemy.url'), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
run_offline() if context.is_offline_mode() else run_online()
