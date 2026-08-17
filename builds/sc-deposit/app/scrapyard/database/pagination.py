"""
pagination — Limit/offset + keyset (cursor) pagination helpers.

### PART-META-JSON
{
  "name": "pagination",
  "layer": "database",
  "purpose": "Pagination helpers for SQLAlchemy 2.x select() statements: offset pagination with capped limits, keyset (cursor) pagination with sort key/direction and next-cursor, filter- and policy-scoped pagination, pydantic serialization of pages, bulk pagination, and an audit-hook wrapper.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "An active Session/Connection plus a SQLAlchemy 2.0 select() over a single mapped entity; limit/offset or cursor parameters.",
  "outputs": "Page / CursorPage dataclasses with items, totals, and next_cursor.",
  "files_created": [],
  "security_notes": "Limits are clamped to max_limit so a client cannot request unbounded result sets. Filter/policy/sort field names are resolved via getattr on the mapped entity and raise AttributeError on unknown names — never interpolate raw user input into these without an allow-list. Cursor values are compared as typed column values, not interpolated SQL, so cursors are injection-safe; they are however guessable sequential keys, not opaque tokens.",
  "ai_usage": "Build a select() statement, then call paginate(db, stmt) or paginate_with_cursor(db, stmt, sort_key='id') and return page.to_dict().",
  "example": "page = paginate(session, select(User), limit=20, offset=40)",
  "import_path": "scrapyard.database.pagination"
}
### END-PART-META
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

STATUS = "core"


@dataclass
class Page:
    items: Sequence[Any]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total

    def to_dict(self) -> dict:
        return {"items": list(self.items), "total": self.total,
                "limit": self.limit, "offset": self.offset, "has_more": self.has_more}


@dataclass
class CursorPage(Page):
    next_cursor: Any = None

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["next_cursor"] = self.next_cursor
        return d


def _query_entity(query):
    """Return the mapped entity class a 2.0-style select() is built over."""
    descriptions = query.column_descriptions
    if not descriptions or descriptions[0].get("entity") is None:
        raise ValueError("query must select a single mapped entity")
    return descriptions[0]["entity"]


def paginate(db, query, *, limit: int = 50, offset: int = 0, max_limit: int = 200) -> Page:
    """Offset-paginate a SQLAlchemy 2.0 select(). Caps limit defensively."""
    from sqlalchemy import func, select
    limit = max(1, min(limit, max_limit))
    offset = max(0, offset)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.limit(limit).offset(offset)).all()
    return Page(items=rows, total=total, limit=limit, offset=offset)


def apply_pagination(db, query, *, limit: int = 50, offset: int = 0) -> tuple[Any, int]:
    """Apply limit/offset to a select() and return ``(paginated_query, total)``.

    ``db`` (Session) is required to compute the total; 2.0-style selects carry
    no session of their own.
    """
    from sqlalchemy import func, select
    if limit < 1:
        raise ValueError("Limit must be at least 1.")
    if offset < 0:
        raise ValueError("Offset must be non-negative.")
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    paginated_query = query.offset(offset).limit(limit)
    return (paginated_query, total)


def paginate_with_cursor(db, query, *, limit: int = 50, cursor: Any = None,
                         max_limit: int = 200, sort_key: str = "id",
                         sort_order: str = "asc") -> CursorPage:
    """Keyset (cursor) pagination over a select().

    Orders by ``sort_key`` (asc/desc), resumes strictly after ``cursor`` when
    given, and returns a CursorPage whose ``next_cursor`` is the last row's
    sort-key value (None when the page is not full).
    """
    from sqlalchemy import func, select
    if limit > max_limit:
        raise ValueError(f"Limit must not exceed {max_limit}.")
    if limit < 1:
        raise ValueError("Limit must be at least 1.")
    if sort_order not in ("asc", "desc"):
        raise ValueError("sort_order must be 'asc' or 'desc'")

    entity = _query_entity(query)
    column = getattr(entity, sort_key)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    keyset_query = query
    if cursor is not None:
        keyset_query = keyset_query.where(column > cursor if sort_order == "asc" else column < cursor)
    keyset_query = keyset_query.order_by(column.asc() if sort_order == "asc" else column.desc())

    rows = db.scalars(keyset_query.limit(limit)).all()
    next_cursor = getattr(rows[-1], sort_key) if len(rows) == limit else None
    return CursorPage(items=rows, total=total, limit=limit, offset=0, next_cursor=next_cursor)


def paginate_with_filters(db, query, filters: dict, *, limit: int = 50,
                          offset: int = 0, max_limit: int = 200) -> Page:
    """Apply equality filters (column name -> value) before paginating."""
    entity = _query_entity(query)
    for key, value in filters.items():
        query = query.where(getattr(entity, key) == value)
    return paginate(db, query, limit=limit, offset=offset, max_limit=max_limit)


def paginate_and_serialize(db, query, serializer, *, limit: int = 50,
                           offset: int = 0, max_limit: int = 200) -> Page:
    """Paginate, then serialize each row through a pydantic v2 model class."""
    page = paginate(db, query, limit=limit, offset=offset, max_limit=max_limit)
    serialized_items = [serializer.model_validate(item, from_attributes=True)
                        for item in page.items]
    return Page(items=serialized_items, total=page.total, limit=page.limit, offset=page.offset)


def bulk_paginate(db, queries, *, limit: int = 50, offset: int = 0, max_limit: int = 200) -> list:
    """Paginate a list of queries; returns a list of Page objects."""
    return [paginate(db, q, limit=limit, offset=offset, max_limit=max_limit) for q in queries]


def paginate_with_audit_hook(db, query, *, limit: int = 50, offset: int = 0,
                             max_limit: int = 200,
                             hook: Optional[Callable[[Page], None]] = None) -> Page:
    """Paginate and pass the resulting Page to an optional audit hook."""
    page = paginate(db, query, limit=limit, offset=offset, max_limit=max_limit)
    if hook is not None and callable(hook):
        hook(page)
    return page


def paginate_with_policy(db, query, policy: dict, *, limit: int = 50,
                         offset: int = 0, max_limit: int = 200) -> Page:
    """Restrict results to policy allow-lists (column name -> allowed values), then paginate."""
    entity = _query_entity(query)
    for key, allowed in policy.items():
        query = query.where(getattr(entity, key).in_(allowed))
    return paginate(db, query, limit=limit, offset=offset, max_limit=max_limit)


def _selftest() -> None:
    from sqlalchemy import Integer, String, create_engine, select
    from sqlalchemy.orm import DeclarativeBase, Session, mapped_column

    class Base(DeclarativeBase):
        pass

    class Thing(Base):
        __tablename__ = "pagination_things"
        id = mapped_column(Integer, primary_key=True)
        name = mapped_column(String(50))
        group = mapped_column(String(10))

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all([Thing(id=i, name=f"t{i}", group="even" if i % 2 == 0 else "odd")
                    for i in range(1, 26)])
        db.flush()

        # offset pagination
        page = paginate(db, select(Thing), limit=10, offset=0)
        assert page.total == 25 and len(page.items) == 10 and page.has_more
        last = paginate(db, select(Thing), limit=10, offset=20)
        assert len(last.items) == 5 and not last.has_more
        assert paginate(db, select(Thing), limit=9999, max_limit=7).limit == 7
        d = page.to_dict()
        assert d["total"] == 25 and d["has_more"] is True

        # apply_pagination returns (query, total) in THAT order
        q2, total = apply_pagination(db, select(Thing), limit=3, offset=1)
        rows = db.scalars(q2).all()
        assert total == 25 and len(rows) == 3 and rows[0].id == 2
        for bad_kwargs in ({"limit": 0}, {"offset": -1}):
            try:
                apply_pagination(db, select(Thing), **bad_kwargs)
                raise AssertionError("bad pagination args accepted")
            except ValueError:
                pass

        # cursor pagination walks the whole set exactly once, asc
        seen: list[int] = []
        cursor = None
        while True:
            cpage = paginate_with_cursor(db, select(Thing), limit=10, cursor=cursor)
            seen.extend(t.id for t in cpage.items)
            assert cpage.total == 25
            if cpage.next_cursor is None:
                break
            cursor = cpage.next_cursor
        assert seen == list(range(1, 26))
        # desc order resumes correctly too
        c1 = paginate_with_cursor(db, select(Thing), limit=5, sort_order="desc")
        assert [t.id for t in c1.items] == [25, 24, 23, 22, 21] and c1.next_cursor == 21
        c2 = paginate_with_cursor(db, select(Thing), limit=5, cursor=c1.next_cursor, sort_order="desc")
        assert [t.id for t in c2.items] == [20, 19, 18, 17, 16]
        assert "next_cursor" in c1.to_dict()
        try:
            paginate_with_cursor(db, select(Thing), limit=500, max_limit=100)
            raise AssertionError("limit above max accepted")
        except ValueError:
            pass
        try:
            paginate_with_cursor(db, select(Thing), sort_order="sideways")
            raise AssertionError("bad sort order accepted")
        except ValueError:
            pass

        # filters + policy
        evens = paginate_with_filters(db, select(Thing), {"group": "even"}, limit=50)
        assert evens.total == 12 and all(t.group == "even" for t in evens.items)
        pol = paginate_with_policy(db, select(Thing), {"id": [1, 2, 3]}, limit=50)
        assert pol.total == 3 and [t.id for t in pol.items] == [1, 2, 3]

        # serialization via pydantic v2
        from pydantic import BaseModel

        class ThingOut(BaseModel):
            id: int
            name: str

        spage = paginate_and_serialize(db, select(Thing), ThingOut, limit=2)
        assert isinstance(spage.items[0], ThingOut) and spage.items[0].name == "t1"

        # bulk + audit hook
        pages = bulk_paginate(db, [select(Thing), select(Thing).where(Thing.group == "odd")], limit=5)
        assert pages[0].total == 25 and pages[1].total == 13
        audited: list[Page] = []
        paginate_with_audit_hook(db, select(Thing), limit=1, hook=audited.append)
        assert len(audited) == 1 and audited[0].total == 25

    print("pagination selftest: PASS")


if __name__ == "__main__":
    _selftest()
