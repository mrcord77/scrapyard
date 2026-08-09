"""
faceted_search — Facet counts/aggregations for filters.

### PART-META-JSON
{
  "name": "faceted_search",
  "layer": "search",
  "purpose": "Facet counts/aggregations for filters.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: facet_counts(db, model, field, filters); facet_values(db, model, field, filters); facet_paginated(db, model, field, page, per_page, filters); facet_counts_with_filters(db, model, field, filters, limit); bulk_facet_counts(db, model, fields, filters) (plus more).",
  "outputs": "Returns: facet_counts -> dict; facet_values -> List[Any]; facet_paginated -> Tuple[List[Any], int]; facet_counts_with_filters -> dict; bulk_facet_counts -> Dict[str, Dict[Any, int]].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `facet_counts` from `scrapyard.search.faceted_search` and call it as shown in `example`; run `py -m scrapyard.search.faceted_search` to see its offline selftest.",
  "example": "from scrapyard.search.faceted_search import facet_counts",
  "import_path": "scrapyard.search.faceted_search"
}
### END-PART-META
"""
from typing import Optional, Dict, List, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, select

def facet_counts(db: Session, model, field: str, filters: Optional[Dict[str, Any]] = None) -> dict:
    """Return {value: count} for a column — the building block of facet UIs."""
    col = getattr(model, field, None)
    if col is None:
        return {}
    
    query = select(col, func.count()).group_by(col)
    if filters:
        query = query.where(**filters)
    
    rows = db.execute(query).all()
    return {r[0]: r[1] for r in rows}

def facet_values(db: Session, model, field: str, filters: Optional[Dict[str, Any]] = None) -> List[Any]:
    """Return distinct values for a field, optionally filtered."""
    query = select(getattr(model, field)).distinct()
    if filters:
        query = query.where(**filters)
    
    rows = db.execute(query).scalars().all()
    return rows

def facet_paginated(db: Session, model, field: str, page: int = 1, per_page: int = 20, filters: Optional[Dict[str, Any]] = None) -> Tuple[List[Any], int]:
    """Returns paginated distinct values and total count for a field."""
    query = select(getattr(model, field)).distinct()
    if filters:
        query = query.where(**filters)
    
    total_count = db.execute(select(func.count()).select_from(query.subquery())).scalar()
    rows = db.execute(query.offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return rows, total_count

def facet_counts_with_filters(db: Session, model, field: str, filters: Optional[Dict[str, Any]] = None, limit: int = 100) -> dict:
    """Returns facet counts with nested query filters and optional result limit."""
    col = getattr(model, field, None)
    if col is None:
        return {}
    
    query = select(col, func.count()).group_by(col).where(**(filters or {})).limit(limit)
    rows = db.execute(query).all()
    return {r[0]: r[1] for r in rows}

def bulk_facet_counts(db: Session, model, fields: List[str], filters: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[Any, int]]:
    """Returns facet counts for multiple fields in a single query."""
    results = {}
    for field in fields:
        col = getattr(model, field, None)
        if col is not None:
            query = select(col, func.count()).group_by(col).where(**(filters or {}))
            rows = db.execute(query).all()
            results[field] = {r[0]: r[1] for r in rows}
    return results

def facet_counts_with_sort(db: Session, model, field: str, sort: str = 'count', filters: Optional[Dict[str, Any]] = None) -> dict:
    """Returns facet counts sorted by count or value."""
    col = getattr(model, field, None)
    if col is None:
        return {}
    
    query = select(col, func.count()).group_by(col).where(**(filters or {}))
    if sort == 'count':
        query = query.order_by(func.count().desc())
    elif sort == 'value':
        query = query.order_by(col.asc())
    
    rows = db.execute(query).all()
    return {r[0]: r[1] for r in rows}

def facet_counts_with_hints(db: Session, model, field: str, filters: Optional[Dict[str, Any]] = None, limit: int = 10) -> dict:
    """Returns top N facet values with counts for UI suggestions."""
    col = getattr(model, field, None)
    if col is None:
        return {}
    
    query = select(col, func.count()).group_by(col).where(**(filters or {})).order_by(func.count().desc()).limit(limit)
    rows = db.execute(query).all()
    return {r[0]: r[1] for r in rows}

def facet_counts_with_audit_hook(db: Session, model, field: str, filters: Optional[Dict[str, Any]] = None, audit_data: Optional[Dict] = None) -> dict:
    """Adds audit logging for facet queries."""
    col = getattr(model, field, None)
    if col is None:
        return {}
    
    query = select(col, func.count()).group_by(col).where(**(filters or {}))
    rows = db.execute(query).all()
    
    # Log the query and results
    from scrapyard.utils.logging import log_audit_event
    log_audit_event(audit_data, f"Facet Query: {query}")

    return {r[0]: r[1] for r in rows}


def _selftest() -> None:
    """Offline self-test: build a real table and assert facet counts/values are
    exact, including a sort-by-count ordering check and an unknown-field guard."""
    from sqlalchemy import Integer, String, create_engine
    from sqlalchemy.orm import DeclarativeBase, Session, mapped_column

    class B(DeclarativeBase):
        pass

    class Item(B):
        __tablename__ = "facet_items"
        id = mapped_column(Integer, primary_key=True)
        color = mapped_column(String(20))

    engine = create_engine("sqlite://")
    B.metadata.create_all(engine)

    with Session(engine) as db:
        # 3 red, 2 blue, 1 green
        colors = ["red"] * 3 + ["blue"] * 2 + ["green"]
        db.add_all([Item(id=i + 1, color=c) for i, c in enumerate(colors)])
        db.flush()

        counts = facet_counts(db, Item, "color")
        assert counts == {"red": 3, "blue": 2, "green": 1}, f"facet counts wrong: {counts}"

        # Distinct values.
        vals = set(facet_values(db, Item, "color"))
        assert vals == {"red", "blue", "green"}, f"facet values wrong: {vals}"

        # Sorted-by-count returns the dominant value first.
        ordered = list(facet_counts_with_sort(db, Item, "color", sort="count").items())
        assert ordered[0] == ("red", 3), f"sort-by-count wrong: {ordered}"

        # Top-N hint limits results to the requested count.
        top1 = facet_counts_with_hints(db, Item, "color", limit=1)
        assert top1 == {"red": 3}, f"top-1 hint wrong: {top1}"

        # Negative/adversarial: an unknown field yields {} rather than crashing.
        assert facet_counts(db, Item, "no_such_field") == {}

    print("faceted_search selftest: PASS")


if __name__ == "__main__":
    _selftest()
