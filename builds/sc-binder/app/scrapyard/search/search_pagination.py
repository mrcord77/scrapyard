"""
search_pagination — Pagination tuned for search result sets.

### PART-META-JSON
{
  "name": "search_pagination",
  "layer": "search",
  "purpose": "Pagination tuned for search result sets.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: search_page(db, query, *, limit, offset).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `search_page` from `scrapyard.search.search_pagination` and call it as shown in `example`; run `py -m scrapyard.search.search_pagination` to see its offline selftest.",
  "example": "from scrapyard.search.search_pagination import search_page",
  "import_path": "scrapyard.search.search_pagination"
}
### END-PART-META
"""
from __future__ import annotations
from sqlalchemy.orm import Session, Query
from scrapyard.database.pagination import paginate

def search_page(db, query, *, limit: int = 20, offset: int = 0):
    """Thin wrapper over database.pagination so search results paginate
    identically to the rest of the app."""
    return paginate(db, query, limit=limit, offset=offset)


def _selftest() -> None:
    """Offline self-test: page through a real result set and assert page 2 is the
    correct slice, plus out-of-range handling."""
    from sqlalchemy import Integer, String, create_engine, select
    from sqlalchemy.orm import DeclarativeBase, Session, mapped_column

    class B(DeclarativeBase):
        pass

    class Row(B):
        __tablename__ = "search_pag_rows"
        id = mapped_column(Integer, primary_key=True)
        name = mapped_column(String(20))

    engine = create_engine("sqlite://")
    B.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all([Row(id=i, name=f"r{i}") for i in range(1, 24)])  # 23 rows
        db.flush()

        stmt = select(Row).order_by(Row.id)

        # Page 1 (offset 0, limit 10) -> ids 1..10, total 23, has_more.
        p1 = search_page(db, stmt, limit=10, offset=0)
        assert p1.total == 23
        assert [r.id for r in p1.items] == list(range(1, 11)), f"page1 wrong: {[r.id for r in p1.items]}"
        assert p1.has_more is True

        # Page 2 (offset 10) -> ids 11..20.
        p2 = search_page(db, stmt, limit=10, offset=10)
        assert [r.id for r in p2.items] == list(range(11, 21)), f"page2 wrong: {[r.id for r in p2.items]}"

        # Page 3 (offset 20) -> ids 21..23, no more.
        p3 = search_page(db, stmt, limit=10, offset=20)
        assert [r.id for r in p3.items] == [21, 22, 23]
        assert p3.has_more is False

        # Negative/adversarial: an out-of-range offset yields an empty page, not an
        # error, and reports no more results.
        p_oob = search_page(db, stmt, limit=10, offset=1000)
        assert p_oob.items == [] and p_oob.total == 23 and p_oob.has_more is False

    print("search_pagination selftest: PASS")


if __name__ == "__main__":
    _selftest()
