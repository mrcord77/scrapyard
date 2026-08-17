"""
retention_policy — Auto-expire data per retention rules.

### PART-META-JSON
{
  "name": "retention_policy",
  "layer": "compliance",
  "purpose": "Auto-expire data per retention rules.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: RetentionPolicy(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `RetentionPolicy` from `scrapyard.compliance.retention_policy` and call it as shown in `example`; run `py -m scrapyard.compliance.retention_policy` to see its offline selftest.",
  "example": "from scrapyard.compliance.retention_policy import RetentionPolicy",
  "import_path": "scrapyard.compliance.retention_policy"
}
### END-PART-META
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

class RetentionPolicy:
    """Declarative retention: {table_or_model: max_age_days}. purge() deletes rows
    older than the limit using a timestamp column (default 'created_at')."""
    def __init__(self, rules: dict | None = None, ts_column: str = "created_at"):
        self.rules = rules or {}; self.ts_column = ts_column
    def purge(self, db, model, days: int | None = None) -> int:
        days = days if days is not None else self.rules.get(model.__tablename__)
        if not days:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        col = getattr(model, self.ts_column)
        rows = db.scalars(select(model).where(col < cutoff)).all()
        for r in rows:
            db.delete(r)
        db.flush()
        return len(rows)


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from sqlalchemy import create_engine, Integer, DateTime
    from sqlalchemy.orm import Session, mapped_column
    from scrapyard.database.base_model import IntPKModel

    global _RetentionRow
    try:
        _RetentionRow
    except NameError:
        class _RetentionRow(IntPKModel):
            __tablename__ = "retention_policy_selftest_rows"
            created_at = mapped_column(DateTime(timezone=True), nullable=False)
            value = mapped_column(Integer, nullable=False, default=0)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                now = datetime.now(timezone.utc)
                db.add_all([
                    _RetentionRow(created_at=now - timedelta(days=100), value=1),
                    _RetentionRow(created_at=now - timedelta(days=40), value=2),
                    _RetentionRow(created_at=now - timedelta(days=5), value=3),
                ])
                db.commit()

                policy = RetentionPolicy({"retention_policy_selftest_rows": 30})
                # No rule / days=None for unknown table -> 0 removed
                class _Fake:
                    __tablename__ = "unknown_table"
                assert policy.purge(db, _RetentionRow, days=None) == 2  # 100d + 40d rows
                db.commit()
                remaining = db.scalars(select(_RetentionRow)).all()
                assert [r.value for r in remaining] == [3]

                # Explicit days override
                assert policy.purge(db, _RetentionRow, days=1) == 1
                db.commit()
                assert db.scalars(select(_RetentionRow)).all() == []

                # Table without a rule is untouched
                empty_policy = RetentionPolicy()
                assert empty_policy.purge(db, _RetentionRow) == 0
        finally:
            engine.dispose()
    print("retention_policy self-test passed")


if __name__ == "__main__":
    _selftest()
