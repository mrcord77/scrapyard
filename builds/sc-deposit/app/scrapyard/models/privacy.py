"""Generated data-subject helpers (export + erasure) for domain-owned tables.
The domain models live in their own DeclarativeBase registry, invisible to the
library identity export/deletion; this module closes that gap."""
from __future__ import annotations
from sqlalchemy import select, delete, inspect as _inspect
from .models import Tenancy, EvidenceShot, Deduction, DisputeLetter


OWNED = [(Tenancy, 'user_id'), (EvidenceShot, 'user_id'), (Deduction, 'user_id'), (DisputeLetter, 'user_id')]


def _ser(v):
    from datetime import datetime, date
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def export_user_data(db, user_id: int) -> dict:
    """All domain rows owned by the user, keyed by table (DSAR / portability)."""
    out = {}
    for model, owner in OWNED:
        rows = db.scalars(select(model).where(getattr(model, owner) == user_id)).all()
        if rows:
            out[model.__tablename__] = [
                {c.key: _ser(getattr(r, c.key)) for c in _inspect(model).columns} for r in rows]
    return out


def stream_user_data(db, user_id: int):
    """Stream every domain row owned by the user as NDJSON — one JSON record per
    line, pulled with a server-side cursor (yield_per) so memory stays bounded
    regardless of account size. Each line carries its source table as '_table'."""
    import json
    for model, owner in OWNED:
        cols = [c.key for c in _inspect(model).columns]
        q = select(model).where(getattr(model, owner) == user_id).execution_options(yield_per=200)
        for r in db.scalars(q):
            rec = {'_table': model.__tablename__}
            for k in cols:
                rec[k] = _ser(getattr(r, k))
            yield json.dumps(rec, default=str) + '\n'


def delete_user_data(db, user_id: int) -> dict:
    """Erase all domain rows owned by the user (right to erasure). Per-table counts."""
    counts = {}
    for model, owner in OWNED:
        res = db.execute(delete(model).where(getattr(model, owner) == user_id))
        counts[model.__tablename__] = res.rowcount or 0
    db.flush()
    return counts