"""
query_helpers — Common filter/sort/search query builders.

### PART-META-JSON
{
  "name": "query_helpers",
  "layer": "database",
  "purpose": "Common filter/sort/search query builders.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: get_or_404(db, model, id_); exists(db, model, **filters); count(db, model, **filters); paginate_query(query, page, per_page); apply_policy(query, policy); FilterQuery(...) (plus more).",
  "outputs": "Returns: exists -> bool; count -> int; paginate_query -> Dict[str, Any]; apply_policy -> List[MappedAsDataclass]; add_audit_hook -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `get_or_404` from `scrapyard.database.query_helpers` and call it as shown in `example`; run `py -m scrapyard.database.query_helpers` to see its offline selftest.",
  "example": "from scrapyard.database.query_helpers import get_or_404",
  "import_path": "scrapyard.database.query_helpers"
}
### END-PART-META
"""
from __future__ import annotations
from sqlalchemy import select, func
from sqlalchemy.orm import Session

def get_or_404(db, model, id_):
    obj = db.get(model, id_)
    if obj is None:
        from fastapi import HTTPException
        raise HTTPException(404, f"{model.__name__} not found")
    return obj

def exists(db, model, **filters) -> bool:
    q = select(model)
    for k, v in filters.items():
        q = q.where(getattr(model, k) == v)
    return db.scalars(q.limit(1)).first() is not None

def count(db, model, **filters) -> int:
    q = select(func.count()).select_from(model)
    for k, v in filters.items():
        q = q.where(getattr(model, k) == v)
    return db.scalar(q) or 0

from typing import Any, List, Dict, Type, Callable, Optional
from sqlalchemy.orm import MappedAsDataclass, declarative_base
from sqlalchemy import and_, or_
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

Base = declarative_base()

class FilterQuery:
    @staticmethod
    def build_filter_query(model: Type[Base], filters: Dict[str, Any], *, allow_null: bool = False) -> List[MappedAsDataclass]:
        conditions = []
        for key, value in filters.items():
            field = getattr(model, key)
            if isinstance(value, dict):
                operator = list(value.keys())[0]
                condition = {f"{key}__{operator}": value[operator]}
            else:
                condition = {key: value}
            conditions.append(field ** condition)

        return and_(*conditions) if conditions else None

    @staticmethod
    def build_sort_query(model: Type[Base], sort_by: List[str], *, default_sort: Optional[str] = None) -> List[MappedAsDataclass]:
        sort_conditions = []
        for field in sort_by:
            try:
                field_obj = getattr(model, field)
                if isinstance(field_obj.property.columns[0].type, str):
                    raise ValueError("Invalid sort field")
                sort_conditions.append(getattr(model, field))
            except AttributeError:
                raise ValueError(f"Invalid sort field: {field}")
        return sort_conditions or [model.id] if default_sort is None else [getattr(model, default_sort)]

    @staticmethod
    def build_search_query(model: Type[Base], search_term: str, fields: List[str]) -> List[MappedAsDataclass]:
        conditions = []
        for field in fields:
            try:
                field_obj = getattr(model, field)
                if not isinstance(field_obj.property.columns[0].type, str):
                    raise ValueError("Search only supported on string fields")
                conditions.append(getattr(model, field).ilike(f"%{search_term}%"))
            except AttributeError:
                raise ValueError(f"Invalid search field: {field}")
        return or_(*conditions)

def paginate_query(query: List[MappedAsDataclass], page: int = 1, per_page: int = 20) -> Dict[str, Any]:
    if per_page <= 0:
        raise ValueError("PerPage must be > 0")
    offset = (page - 1) * per_page
    total = len(query)
    items = query[offset:offset + per_page]
    return {"total": total, "items": items}

def apply_policy(query: List[MappedAsDataclass], policy: Callable[[List[MappedAsDataclass]], List[MappedAsDataclass]]) -> List[MappedAsDataclass]:
    return policy(query)

def add_audit_hook(query: List[MappedAsDataclass], *, user_id: int, action: str) -> None:
    from scrapyard.logging import log_query
    log_query(user_id, action, query)

def bulk_create(db: Session, model: Type[Base], items: List[Dict[str, Any]]) -> List[Base]:
    created_items = []
    for item_data in items:
        try:
            new_item = model(**item_data)
            db.add(new_item)
            created_items.append(new_item)
        except ValidationError as e:
            raise ValueError(f"Invalid data for {model.__name__}: {e}")
        except IntegrityError:
            db.rollback()
            raise ValueError(f"Duplicate primary key for {model.__name__}")
    db.commit()
    return created_items

def bulk_update(db: Session, model: Type[Base], items: List[Dict[str, Any]], id_field: str) -> None:
    for item_data in items:
        try:
            obj = db.query(model).filter(getattr(model, id_field) == item_data[id_field]).first()
            if not obj:
                raise ValueError(f"{model.__name__} with ID {item_data[id_field]} not found")
            for key, value in item_data.items():
                setattr(obj, key, value)
            flag_modified(obj, key)
        except KeyError:
            raise ValueError(f"Missing required field: {id_field}")
    db.commit()

def build_archive_query(model: Type[Base], is_archived: bool = True) -> List[MappedAsDataclass]:
    return [getattr(model, "is_archived") == is_archived]

def serialize_query_results(query: List[MappedAsDataclass], model: Type[Base], schema: Type[BaseModel]) -> List[Dict[str, Any]]:
    results = []
    for item in query:
        try:
            serialized_item = schema.from_orm(item)
            results.append(serialized_item.dict())
        except ValidationError as e:
            raise ValueError(f"Failed to serialize {model.__name__}: {e}")
    return results


def _selftest() -> None:
    from sqlalchemy import create_engine, String, Column
    from sqlalchemy.orm import sessionmaker
    from scrapyard.database.base_model import Base as SABase, IntPKModel
    from fastapi import HTTPException

    class Product(IntPKModel):                            # imperative column: no annotation eval needed
        __tablename__ = "query_helpers_selftest_product"
        name = Column(String(20))

    engine = create_engine("sqlite:///:memory:")
    SABase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([Product(name="a"), Product(name="b"), Product(name="a")]); db.commit()

    assert count(db, Product) == 3
    assert count(db, Product, name="a") == 2              # filtered count
    assert exists(db, Product, name="a") is True
    assert exists(db, Product, name="zzz") is False       # negative: no match
    assert get_or_404(db, Product, 1).id == 1
    try:                                                  # negative: missing row -> HTTP 404
        get_or_404(db, Product, 999)
        raise AssertionError("get_or_404 did not raise on a missing row")
    except HTTPException as e:
        assert e.status_code == 404

    assert paginate_query([1, 2, 3, 4, 5], page=2, per_page=2) == {"total": 5, "items": [3, 4]}
    try:                                                  # negative: per_page must be > 0
        paginate_query([1], page=1, per_page=0)
        raise AssertionError("paginate_query accepted per_page=0")
    except ValueError:
        pass
    db.close()
    print("query_helpers selftest: PASS")


if __name__ == "__main__":
    _selftest()
