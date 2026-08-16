"""Generated retention wiring — auto-expire data per the domain's retention_days. Idempotent: only deletes rows past their max age."""
from scrapyard.compliance.retention_policy import RetentionPolicy
from scrapyard.models import models as _M

RETENTION_RULES = {'encounters': 2555}

def _models_by_table():
    out = {}
    for _n in dir(_M):
        obj = getattr(_M, _n)
        tbl = getattr(obj, '__tablename__', None)
        if tbl:
            out[tbl] = obj
    return out

def run_retention(db) -> dict:
    policy = RetentionPolicy(RETENTION_RULES)
    by_table = _models_by_table()
    purged = {}
    for table, days in RETENTION_RULES.items():
        model = by_table.get(table)
        if model is None:
            continue
        purged[table] = policy.purge(db, model, days)
    db.commit()
    return purged
