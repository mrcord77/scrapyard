"""
soft_delete — Mixin + query filter for soft deletes.

### PART-META-JSON
{
  "name": "soft_delete",
  "layer": "database",
  "purpose": "Mixin + query filter for soft deletes.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: only_alive(query); SoftDeleteMixin(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `only_alive` from `scrapyard.database.soft_delete` and call it as shown in `example`; run `py -m scrapyard.database.soft_delete` to see its offline selftest.",
  "example": "from scrapyard.database.soft_delete import only_alive",
  "import_path": "scrapyard.database.soft_delete"
}
### END-PART-META
"""
from __future__ import annotations
from datetime import datetime, timezone

STATUS = "core"

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


class SoftDeleteMixin:
    """Adds deleted_at; rows with a value are considered deleted."""
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self) -> None:
        self.deleted_at = None


def only_alive(query):
    """Filter a SQLAlchemy select() to rows that are not soft-deleted."""
    entity = query.column_descriptions[0]["entity"]
    return query.filter(entity.deleted_at.is_(None))


def _selftest() -> None:
    from sqlalchemy import create_engine, String, select
    from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
    from scrapyard.database.base_model import Base, IntPKModel

    class Note(SoftDeleteMixin, IntPKModel):
        __tablename__ = "soft_delete_selftest_note"
        body: Mapped[str] = mapped_column(String(50))

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    a, b = Note(body="keep"), Note(body="drop")
    db.add_all([a, b]); db.commit()

    b.soft_delete(); db.commit()
    assert b.is_deleted and not a.is_deleted
    alive = db.scalars(only_alive(select(Note))).all()
    assert [n.body for n in alive] == ["keep"]            # deleted row excluded by default
    assert len(db.scalars(select(Note)).all()) == 2       # still present with include_deleted

    b.restore(); db.commit()
    assert len(db.scalars(only_alive(select(Note))).all()) == 2   # restore un-hides it
    db.close()
    print("soft_delete selftest: PASS")


if __name__ == "__main__":
    _selftest()
