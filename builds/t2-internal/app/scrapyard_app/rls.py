"""Per-request row-level-security context.

When RLS is enforced (SCRAPYARD_RLS=enforce on PostgreSQL), every scoped query
must run inside a transaction that has set the current principal, or the
fail-closed policies return zero rows. Use rls_session() per request.
"""
from contextlib import contextmanager
from scrapyard.database.db_session import get_sessionmaker
from scrapyard.security.row_level_security import set_context

@contextmanager
def rls_session(*, user_id=None, tenant_id=None):
    """Yield a DB session bound to the principal; context is transaction-local."""
    Session = get_sessionmaker()
    db = Session()
    try:
        db.begin()
        set_context(db.connection(), user_id=user_id, tenant_id=tenant_id)
        yield db
        db.commit()
    except Exception:
        db.rollback(); raise
    finally:
        db.close()
