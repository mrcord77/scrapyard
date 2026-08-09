"""
unit_of_work — Explicit UoW boundary around repositories.

### PART-META-JSON
{
  "name": "unit_of_work",
  "layer": "database",
  "purpose": "Explicit UoW boundary around repositories.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: UnitOfWork(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `UnitOfWork` from `scrapyard.database.unit_of_work` and call it as shown in `example`; run `py -m scrapyard.database.unit_of_work` to see its offline selftest.",
  "example": "from scrapyard.database.unit_of_work import UnitOfWork",
  "import_path": "scrapyard.database.unit_of_work"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

class UnitOfWork:
    """Collect changes and commit atomically; rollback on error (context manager)."""
    def __init__(self, db):
        self.db = db
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.db.rollback()
        else:
            self.db.commit()
        return False
    def add(self, obj):
        self.db.add(obj); return obj
    def delete(self, obj):
        self.db.delete(obj)


def _selftest() -> None:
    from sqlalchemy import create_engine, String, Integer, Column, select, func
    from sqlalchemy.orm import sessionmaker, DeclarativeBase

    class B(DeclarativeBase):
        pass

    class Item(B):                                        # imperative columns: no annotation eval needed
        __tablename__ = "uow_selftest_item"
        id = Column(Integer, primary_key=True)
        sku = Column(String(20))

    engine = create_engine("sqlite:///:memory:")
    B.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    def n():
        return db.scalar(select(func.count()).select_from(Item))

    with UnitOfWork(db) as uow:                           # clean exit commits
        uow.add(Item(sku="a"))
    assert n() == 1

    try:                                                  # exception rolls the whole unit back
        with UnitOfWork(db) as uow:
            uow.add(Item(sku="b")); db.flush()
            raise RuntimeError("fail mid-work")
    except RuntimeError:
        pass
    assert n() == 1                                       # negative: uncommitted row absent

    with UnitOfWork(db) as uow:                           # delete commits on clean exit
        uow.delete(db.scalar(select(Item)))
    assert n() == 0
    db.close()
    print("unit_of_work selftest: PASS")


if __name__ == "__main__":
    _selftest()
