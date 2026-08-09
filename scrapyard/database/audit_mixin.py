"""
audit_mixin — created_by/updated_by + change tracking mixin.

### PART-META-JSON
{
  "name": "audit_mixin",
  "layer": "database",
  "purpose": "created_by/updated_by + change tracking mixin.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: AuthorshipMixin(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `AuthorshipMixin` from `scrapyard.database.audit_mixin` and call it as shown in `example`; run `py -m scrapyard.database.audit_mixin` to see its offline selftest.",
  "example": "from scrapyard.database.audit_mixin import AuthorshipMixin",
  "import_path": "scrapyard.database.audit_mixin"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

class AuthorshipMixin:
    """Adds created_by / updated_by user id columns for traceability."""
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    def stamp(self, user_id: int, *, creating: bool = False):
        if creating:
            self.created_by = user_id
        self.updated_by = user_id


def _selftest() -> None:
    from sqlalchemy import create_engine, String
    from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
    from scrapyard.database.base_model import Base, IntPKModel

    class Doc(AuthorshipMixin, IntPKModel):
        __tablename__ = "audit_mixin_selftest_doc"
        title: Mapped[str] = mapped_column(String(50))

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    d = Doc(title="spec")
    assert d.created_by is None and d.updated_by is None  # negative: unset before stamping
    d.stamp(7, creating=True)
    db.add(d); db.commit()
    assert d.created_by == 7 and d.updated_by == 7        # creating stamps both authors
    d.stamp(9)                                            # a later edit by another user
    db.commit()
    assert d.created_by == 7                              # original author preserved
    assert d.updated_by == 9                              # editor recorded
    db.close()
    print("audit_mixin selftest: PASS")


if __name__ == "__main__":
    _selftest()
