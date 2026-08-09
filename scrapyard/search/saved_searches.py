"""
saved_searches — Persist + replay user search definitions.

### PART-META-JSON
{
  "name": "saved_searches",
  "layer": "search",
  "purpose": "Persists and replays user search definitions in a SQLAlchemy-backed saved_searches table: per-user CRUD (create/get/update/soft-delete, bulk variants), paginated listing with sorting/filtering, JSON-serialized query payloads, and simple text search over stored queries. All accessors are scoped by user_id so one user cannot address another user's rows.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy",
    "scrapyard.database.base_model"
  ],
  "inputs": "A SQLAlchemy Session, user_id, search names, query dicts (JSON-serializable), pagination/sort/filter parameters.",
  "outputs": "SavedSearch ORM rows and plain-dict projections ({id, name, query}); listings return {total, items}.",
  "files_created": [],
  "security_notes": "Row scoping is by user_id in every query - callers MUST pass the authenticated user's id, not a client-supplied one, or the scoping is theater. Sort/field/filter parameters are resolved via getattr on the model and are validated against real column names, raising ValueError for unknown attributes so callers cannot probe arbitrary model attributes. Stored query payloads are user-controlled JSON: replaying them against a search engine must re-validate them at replay time (stored-query injection). Deletes are soft (is_deleted flag) - data remains in the table, so purging for privacy/GDPR requires a separate hard-delete sweep.",
  "ai_usage": "save(db, user_id, name, query) / list_for(db, user_id) for the simple path; create/get/update/delete_saved_search + bulk variants for full CRUD; list_saved_searches for pagination.",
  "example": "from scrapyard.search.saved_searches import save, list_for",
  "import_path": "scrapyard.search.saved_searches"
}
### END-PART-META
"""
from __future__ import annotations
import json
from typing import Optional, List, Dict, Any
from sqlalchemy import Integer, String, Text, select, func
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel

STATUS = "core"

class SavedSearch(IntPKModel):
    __tablename__ = "saved_searches"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(100))
    query_json: Mapped[str] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(default=False)

def save(db: Session, user_id: int, name: str, query: dict) -> SavedSearch:
    s = SavedSearch(user_id=user_id, name=name, query_json=json.dumps(query))
    db.add(s)
    db.flush()
    return s

def list_for(db: Session, user_id: int) -> List[Dict[str, Any]]:
    rows = db.scalars(select(SavedSearch).where(SavedSearch.user_id == user_id, SavedSearch.is_deleted == False)).all()
    return [{"id": r.id, "name": r.name, "query": json.loads(r.query_json)} for r in rows]

def create_saved_search(db: Session, user_id: int, name: str, query: dict, metadata: Optional[dict] = None) -> SavedSearch:
    try:
        apply_policy(db, user_id)
        s = SavedSearch(user_id=user_id, name=name, query_json=json.dumps(query))
        if metadata is not None:
            if metadata.get("user_id") not in (None, user_id):
                raise PermissionError("metadata user_id does not match owner")
        db.add(s)
        db.flush()
        return s
    except Exception as e:
        raise e

def _column_attr(name: str):
    """Resolve a real mapped column attribute by name; ValueError otherwise."""
    if name not in SavedSearch.__table__.columns:
        raise ValueError(f"unknown SavedSearch column: {name!r}")
    return getattr(SavedSearch, name)

def get_saved_search(db: Session, search_id: int, user_id: int, fields: Optional[List[str]] = None) -> Dict[str, Any]:
    row = db.execute(select(SavedSearch).where(SavedSearch.id == search_id, SavedSearch.user_id == user_id, SavedSearch.is_deleted == False)).scalar_one()
    if fields is not None:
        for field in fields:
            _column_attr(field)  # validate against real columns
        return {field: getattr(row, field) for field in fields}
    return {"id": row.id, "name": row.name, "query": json.loads(row.query_json)}

def list_saved_searches(db: Session, user_id: int, page: int = 1, per_page: int = 20, sort: str = "id", filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    query = select(SavedSearch).where(SavedSearch.user_id == user_id, SavedSearch.is_deleted == False)
    if filters is not None:
        for key, value in filters.items():
            query = query.where(_column_attr(key) == value)

    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()
    rows = db.execute(
        query.order_by(_column_attr(sort)).offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()

    return {
        "total": total,
        "items": [{"id": r.id, "name": r.name, "query": json.loads(r.query_json)} for r in rows]
    }

def update_saved_search(db: Session, search_id: int, user_id: int, name: Optional[str] = None, query: Optional[dict] = None, metadata: Optional[dict] = None) -> SavedSearch:
    try:
        s = db.execute(select(SavedSearch).where(SavedSearch.id == search_id, SavedSearch.user_id == user_id, SavedSearch.is_deleted == False)).scalar_one()
        if name is not None:
            s.name = name
        if query is not None:
            s.query_json = json.dumps(query)
        if metadata is not None:
            if metadata.get("user_id") not in (None, user_id):
                raise PermissionError("metadata user_id does not match owner")
        db.add(s)
        db.flush()
        return s
    except Exception as e:
        raise e

def delete_saved_search(db: Session, search_id: int, user_id: int) -> None:
    try:
        s = db.execute(select(SavedSearch).where(SavedSearch.id == search_id, SavedSearch.user_id == user_id, SavedSearch.is_deleted == False)).scalar_one()
        # Soft delete
        s.is_deleted = True
        db.add(s)
        db.flush()
    except Exception as e:
        raise e

def bulk_create_saved_searches(db: Session, user_id: int, searches: List[dict]) -> List[SavedSearch]:
    try:
        saved_searches = [SavedSearch(user_id=user_id, name=s['name'], query_json=json.dumps(s['query'])) for s in searches]
        db.add_all(saved_searches)
        db.flush()
        return saved_searches
    except Exception as e:
        raise e

def bulk_delete_saved_searches(db: Session, search_ids: List[int], user_id: int) -> None:
    try:
        for s in db.query(SavedSearch).filter(SavedSearch.id.in_(search_ids), SavedSearch.user_id == user_id, SavedSearch.is_deleted == False):
            # Soft delete
            s.is_deleted = True
        db.flush()
    except Exception as e:
        raise e

def search_saved_searches(db: Session, user_id: int, query_text: str, metadata_filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    stmt = select(SavedSearch).where(SavedSearch.user_id == user_id, SavedSearch.is_deleted == False)
    if query_text:
        # Simple text search over the stored JSON payload
        stmt = stmt.where(SavedSearch.query_json.contains(query_text))
    if metadata_filters is not None:
        for key, value in metadata_filters.items():
            stmt = stmt.where(_column_attr(key) == value)

    rows = db.scalars(stmt).all()
    return [{"id": r.id, "name": r.name, "query": json.loads(r.query_json)} for r in rows]

def serialize_search(search: SavedSearch, include: Optional[List[str]] = None, exclude: Optional[List[str]] = None) -> Dict[str, Any]:
    serialized = {"id": search.id, "name": search.name, "query": json.loads(search.query_json)}
    if include:
        return {k: v for k, v in serialized.items() if k in include}
    elif exclude:
        return {k: v for k, v in serialized.items() if k not in exclude}
    else:
        return serialized

def deserialize_search(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(json.dumps(data))
    except (ValueError) as e:
        raise e

def apply_policy(db: Session, user_id: int):
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id must be a positive integer")
    count = db.scalar(select(func.count()).select_from(SavedSearch).where(
        SavedSearch.user_id == user_id, SavedSearch.is_deleted == False)) or 0
    if count >= 100:
        raise PermissionError("saved search limit reached")
    return {"user_id": user_id, "active_searches": count, "limit": 100}

def _selftest() -> None:
    """Offline selftest against an in-memory SQLite database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    try:
        SavedSearch.metadata.create_all(engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        with SessionLocal() as db:
            # Create + list (simple path)
            s1 = save(db, 1, "First", {"field": "value"})
            s2 = create_saved_search(db, 1, "Second", {"q": "cats"})
            assert apply_policy(db, 1)["active_searches"] == 2
            try:
                apply_policy(db, 0)
                raise AssertionError("accepted invalid user id")
            except ValueError:
                pass
            _other = save(db, 2, "OtherUser", {"q": "dogs"})
            assert s1.id != s2.id
            items = list_for(db, 1)
            assert [i["name"] for i in items] == ["First", "Second"]
            assert items[0]["query"] == {"field": "value"}

            # get with field projection + validation
            got = get_saved_search(db, s2.id, 1)
            assert got["query"] == {"q": "cats"}
            proj = get_saved_search(db, s2.id, 1, fields=["name", "user_id"])
            assert proj == {"name": "Second", "user_id": 1}
            try:
                get_saved_search(db, s2.id, 1, fields=["__table__"])
                raise AssertionError("non-column field must raise")
            except ValueError:
                pass

            # user scoping: user 2 cannot fetch user 1's row
            try:
                get_saved_search(db, s1.id, 2)
                raise AssertionError("cross-user access must fail")
            except Exception as exc:
                assert "No row was found" in str(exc) or "NoResultFound" in type(exc).__name__

            # pagination + count + sort
            listing = list_saved_searches(db, 1, page=1, per_page=1, sort="name")
            assert listing["total"] == 2 and len(listing["items"]) == 1
            assert listing["items"][0]["name"] == "First"
            page2 = list_saved_searches(db, 1, page=2, per_page=1, sort="name")
            assert page2["items"][0]["name"] == "Second"
            try:
                list_saved_searches(db, 1, sort="no_such_column")
                raise AssertionError("unknown sort column must raise")
            except ValueError:
                pass

            # update
            updated = update_saved_search(db, s1.id, 1, name="Renamed",
                                          query={"new": True})
            assert updated.name == "Renamed"
            assert json.loads(updated.query_json) == {"new": True}

            # text search over stored queries
            found = search_saved_searches(db, 1, "cats")
            assert [f["name"] for f in found] == ["Second"]

            # serialize include/exclude
            ser = serialize_search(s2, include=["name"])
            assert ser == {"name": "Second"}
            ser2 = serialize_search(s2, exclude=["query"])
            assert set(ser2) == {"id", "name"}

            # soft delete hides rows but keeps them addressable in bulk delete
            delete_saved_search(db, s1.id, 1)
            assert [i["name"] for i in list_for(db, 1)] == ["Second"]
            bulk = bulk_create_saved_searches(db, 1, [
                {"name": "B1", "query": {"a": 1}},
                {"name": "B2", "query": {"a": 2}},
            ])
            assert len(bulk) == 2
            bulk_delete_saved_searches(db, [b.id for b in bulk], 1)
            assert [i["name"] for i in list_for(db, 1)] == ["Second"]
            db.commit()
    finally:
        engine.dispose()

    print("saved_searches selftest: all tests passed")


if __name__ == "__main__":
    _selftest()
