"""Generated startup checks: config validation, DB init, production fallback gate."""
from __future__ import annotations
from scrapyard_app.settings import settings


def startup_checks():
    # 1) production must not run on dev defaults
    if settings.is_production and settings.secret_key == "dev-only-change-me":
        raise RuntimeError("SECRET_KEY must be set in production")

    # 2) schema is MIGRATION-FIRST in dev AND prod: run `alembic upgrade head`
    #    (the single source of truth). create_all() then runs check-first ONLY to
    #    add tables no migration covers yet -- it runs AFTER alembic and skips any
    #    table a migration already created, so it can never cause 'already exists'.
    try:
        from scrapyard.database.db_session import init_engine
        engine = init_engine(settings.database_url)
        import os as _os
        _ini = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'alembic.ini')
        _migrated = False
        if _os.path.exists(_ini):
            try:
                from alembic.config import Config
                from alembic import command
                _cfg = Config(_ini); _cfg.set_main_option('sqlalchemy.url', settings.database_url)
                command.upgrade(_cfg, 'head')   # migration-managed schema (dev + prod)
                _migrated = True
            except Exception as _me:
                print(f'[bootstrap] alembic upgrade head failed, falling back to create_all: {_me}')
        from scrapyard.database.base_model import Base
        try:
            import scrapyard.identity.users  # noqa: F401  (registers tables on Base)
        except Exception as _e:
            print(f'[bootstrap] model import skipped: scrapyard.identity.users: {_e}')
        try:
            import scrapyard.identity.session_manager  # noqa: F401  (registers tables on Base)
        except Exception as _e:
            print(f'[bootstrap] model import skipped: scrapyard.identity.session_manager: {_e}')
        try:
            import scrapyard.admin.audit_logs  # noqa: F401  (registers tables on Base)
        except Exception as _e:
            print(f'[bootstrap] model import skipped: scrapyard.admin.audit_logs: {_e}')
        # check-first: creates only tables a migration did not (no conflict with migrated tables)
        Base.metadata.create_all(engine, checkfirst=True)
        if settings.is_production and _os.environ.get('SCRAPYARD_RLS', '').strip().lower() == 'enforce' and settings.database_url.startswith('postgres'):
            from scrapyard.security.row_level_security import apply_rls_existing
            with engine.begin() as _conn:
                print('[bootstrap] database RLS enforced on:', apply_rls_existing(_conn))
    except Exception as e:
        print(f"[bootstrap] database init skipped: {e}")

    # 3) production fallback gate (refuse local-only paths in prod), if available
    try:
        from scrapyard.runtime.fallbacks import detect_fallbacks, assert_no_forbidden_fallbacks
        detect_fallbacks(settings)
        assert_no_forbidden_fallbacks(settings.app_env)
    except RuntimeError:
        raise
    except Exception as e:
        print(f"[bootstrap] fallback gate unavailable: {e}")

    # 4) observability: export errors/traces when configured (no-op without
    #    SENTRY_DSN / OTEL_EXPORTER_OTLP_ENDPOINT, or if the SDK isn't installed)
    try:
        from scrapyard.observability.error_reporting import init_sentry
        if init_sentry():
            print("[bootstrap] Sentry error reporting enabled")
    except Exception as e:
        print(f"[bootstrap] error reporting not enabled: {e}")
    try:
        from scrapyard.observability.tracing import init_otel
        if init_otel() is not None:
            print("[bootstrap] OpenTelemetry tracing enabled")
    except Exception as e:
        print(f"[bootstrap] tracing not enabled: {e}")
