"""
seed_data — Idempotent seed/fixture loader for dev + tests.

### PART-META-JSON
{
  "name": "seed_data",
  "layer": "database",
  "purpose": "Idempotent seed/fixture loader for dev + tests.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: seed(db, model, rows, *, key).",
  "outputs": "Returns: seed -> int.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `seed` from `scrapyard.database.seed_data` and call it as shown in `example`; run `py -m scrapyard.database.seed_data` to see its offline selftest.",
  "example": "from scrapyard.database.seed_data import seed",
  "import_path": "scrapyard.database.seed_data"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

def seed(db, model, rows: list[dict], *, key: str = "id") -> int:
    """Idempotently insert rows that don't already exist (matched on `key`)."""
    inserted = 0
    for row in rows:
        if key in row and db.get(model, row[key]) is not None:
            continue
        db.add(model(**row)); inserted += 1
    db.flush()
    return inserted


def _selftest() -> None:
    from sqlalchemy import create_engine, String, Column, select, func
    from sqlalchemy.orm import sessionmaker
    from scrapyard.database.base_model import Base, IntPKModel

    class City(IntPKModel):                               # imperative column: no annotation eval needed
        __tablename__ = "seed_data_selftest_city"
        name = Column(String(20))

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    def total():
        return db.scalar(select(func.count()).select_from(City))

    rows = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert seed(db, City, rows) == 2; db.commit()         # first run inserts both
    assert seed(db, City, rows) == 0; db.commit()         # idempotent: re-seed inserts nothing
    assert total() == 2                                   # negative: no duplicates

    assert seed(db, City, [{"id": 2, "name": "b"}, {"id": 3, "name": "c"}]) == 1
    db.commit()
    assert total() == 3                                   # only the genuinely new row landed
    db.close()
    print("seed_data selftest: PASS")


if __name__ == "__main__":
    _selftest()
