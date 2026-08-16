"""
migrations — Alembic setup conventions for schema migrations.

### PART-META-JSON
{
  "name": "migrations",
  "layer": "database",
  "purpose": "Alembic setup conventions for schema migrations.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "alembic"
  ],
  "inputs": "Public API: MigrationRecord(...); MigrationRunner(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `MigrationRecord` from `scrapyard.database.migrations` and call it as shown in `example`; run `py -m scrapyard.database.migrations` to see its offline selftest.",
  "example": "from scrapyard.database.migrations import MigrationRecord",
  "import_path": "scrapyard.database.migrations"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel
class MigrationRecord(IntPKModel):
    __tablename__="schema_migrations"
    version: Mapped[str]=mapped_column(String(80), unique=True, index=True)
class MigrationRunner:
    """Ordered, idempotent migrations. Each is (version, fn(connection)). Applied
    versions are tracked so re-running is a no-op. For schema management prefer
    this over create_all in production."""
    def __init__(self, db): self.db=db; self.migrations=[]
    def add(self, version, fn): self.migrations.append((version, fn)); return self
    def applied(self): 
        return {r.version for r in self.db.scalars(select(MigrationRecord))}
    def run(self):
        done=self.applied(); ran=[]
        for version, fn in sorted(self.migrations):
            if version in done: continue
            fn(self.db); self.db.add(MigrationRecord(version=version)); self.db.flush(); ran.append(version)
        return ran


def _selftest() -> None:
    from sqlalchemy import create_engine, String, select
    from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
    from scrapyard.database.base_model import Base, IntPKModel

    class Widget(IntPKModel):
        __tablename__ = "migrations_selftest_widget"
        label: Mapped[str] = mapped_column(String(20))

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    calls = {"n": 0}
    def m001(conn_db):
        calls["n"] += 1
        conn_db.add(Widget(label="seeded"))

    ran = MigrationRunner(db).add("001_init", m001).run(); db.commit()
    assert ran == ["001_init"]                            # applied once
    assert "001_init" in MigrationRunner(db).applied()    # recorded in schema_migrations
    assert calls["n"] == 1

    # re-running is a no-op and must NOT re-invoke the migration fn
    ran2 = MigrationRunner(db).add("001_init", m001).run(); db.commit()
    assert ran2 == []
    assert calls["n"] == 1                                # negative: fn not called again
    assert db.scalar(select(MigrationRecord).where(MigrationRecord.version == "001_init")) is not None
    db.close()
    print("migrations selftest: PASS")


if __name__ == "__main__":
    _selftest()
