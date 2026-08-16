"""
base_model — Declarative base with primary key + common helpers.

### PART-META-JSON
{
  "name": "base_model",
  "layer": "database",
  "purpose": "Declarative base with primary key + common helpers.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: Base(...); IntPKModel(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `Base` from `scrapyard.database.base_model` and call it as shown in `example`; run `py -m scrapyard.database.base_model` to see its offline selftest.",
  "example": "from scrapyard.database.base_model import Base",
  "import_path": "scrapyard.database.base_model"
}
### END-PART-META
"""
from __future__ import annotations

STATUS = "core"

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all models."""


class IntPKModel(Base):
    __abstract__ = True
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    def to_dict(self) -> dict:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


def _selftest() -> None:
    from sqlalchemy import create_engine, String
    from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

    class Widget(IntPKModel):
        __tablename__ = "base_model_selftest_widget"
        name: Mapped[str] = mapped_column(String(50))

    # IntPKModel is abstract: it must never own a table of its own
    assert IntPKModel.__abstract__ is True
    assert Widget.__tablename__ == "base_model_selftest_widget"

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    w = Widget(name="anvil")
    db.add(w); db.commit()
    assert isinstance(w.id, int) and w.id >= 1            # autoincrement PK assigned
    assert w.to_dict() == {"id": w.id, "name": "anvil"}   # to_dict round-trips real columns
    assert db.get(Widget, 99999) is None                  # negative: missing pk -> None
    db.close()
    print("base_model selftest: PASS")


if __name__ == "__main__":
    _selftest()
