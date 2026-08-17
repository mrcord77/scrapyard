"""
filters — Composable, safe filter spec -> query.

### PART-META-JSON
{
  "name": "filters",
  "layer": "search",
  "purpose": "Composable, safe filter spec -> query.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: apply_filters(query, model, filters); apply_filters_with_policy(query, model, filters, policy); build_filter_spec(spec, model); apply_search_filters(query, model, search_term, fields); apply_pagination(query, page, per_page); FilterFieldError(...); FilterOpError(...); FilterValueError(...) (plus more).",
  "outputs": "Returns: apply_filters_with_policy -> Query; build_filter_spec -> List[Dict[str, Union[str, Any]]]; apply_search_filters -> Query; apply_pagination -> Query; apply_sorting -> Query.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `apply_filters` from `scrapyard.search.filters` and call it as shown in `example`; run `py -m scrapyard.search.filters` to see its offline selftest.",
  "example": "from scrapyard.search.filters import apply_filters",
  "import_path": "scrapyard.search.filters"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

from typing import Any, Dict, List, Optional, Type, Union

OPS = {
    "eq": lambda col, v: col == v,
    "ne": lambda col, v: col != v,
    "lt": lambda col, v: col < v,
    "lte": lambda col, v: col <= v,
    "gt": lambda col, v: col > v,
    "gte": lambda col, v: col >= v,
    "in": lambda col, v: col.in_(v),
    "contains": lambda col, v: col.like(f"%{v}%"),
}

def apply_filters(query, model, filters: list[dict]):
    """filters: [{field, op, value}]. Only known columns + ops are honored."""
    for f in filters:
        col = getattr(model, f["field"], None)
        op = OPS.get(f.get("op", "eq"))
        if col is not None and op is not None:
            query = query.where(op(col, f["value"]))
    return query

# --- grafted from enhanced draft (additional functionality) ---
from sqlalchemy.orm import Session, Mapped, mapped_column, Query
from fastapi import Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class FilterFieldError(ValueError):
    pass

class FilterOpError(ValueError):
    pass

class FilterValueError(ValueError):
    pass

OPS_EXTENDED = {
    "eq": lambda col, value: col == value,
    "ne": lambda col, value: col != value,
    "lt": lambda col, value: col < value,
    "le": lambda col, value: col <= value,
    "gt": lambda col, value: col > value,
    "ge": lambda col, value: col >= value
}

class FilterPolicy(BaseModel):
    field_permissions: Dict[str, List[str]]

def apply_filters_with_policy(query: Query, model: Type[Base], filters: List[Dict[str, Union[str, Any]]], policy: FilterPolicy) -> Query:
    for f in filters:
        if f["field"] not in policy.field_permissions.get(model.__tablename__, []):
            raise FilterFieldError(f"Access denied to field {f['field']}")

        col = getattr(model, f["field"], None)
        op = OPS_EXTENDED.get(f.get("op", "eq"))
        if col is not None and op is not None:
            query = query.where(op(col, f["value"]))
    return query

def build_filter_spec(spec: Dict[str, Any], model: Type[Base]) -> List[Dict[str, Union[str, Any]]]:
    filters = []
    for k, v in spec.items():
        if isinstance(v, dict):
            filters.extend(build_filter_spec(v, model))
        else:
            col = getattr(model, k, None)
            if col is not None:
                filters.append({"field": k, "op": "eq", "value": v})
    return filters

def apply_search_filters(query: Query, model: Type[Base], search_term: str, fields: List[str]) -> Query:
    for field in fields:
        col = getattr(model, field, None)
        if col is not None:
            query = query.where(col.like(f"%{search_term}%"))
    return query

def apply_pagination(query: Query, page: int = 1, per_page: int = 25) -> Query:
    offset = (page - 1) * per_page
    return query.offset(offset).limit(per_page)

def apply_sorting(query: Query, model: Type[Base], sort_by: List[str], allow_fields: Optional[List[str]] = None) -> Query:
    for field in sort_by:
        if allow_fields and field not in allow_fields:
            raise ValueError(f"Sorting by {field} is not allowed")
        col = getattr(model, field, None)
        if col is not None:
            query = query.order_by(col)
    return query

def apply_archived_filter(query: Query, model: Type[Base], is_archived: bool = False) -> Query:
    archived_field = "is_archived"  # Assuming a common field name for archiving
    if hasattr(model, archived_field):
        query = query.filter(getattr(model, archived_field) == is_archived)
    return query

def apply_bulk_filters(query: Query, model: Type[Base], filter_specs: List[List[Dict[str, Union[str, Any]]]]) -> Query:
    for spec in filter_specs:
        query = apply_filters_with_policy(query, model, spec, FilterPolicy(field_permissions={model.__tablename__: []}))
    return query

def apply_filter_hooks(query: Query, model: Type[Base], filters: List[Dict[str, Union[str, Any]]], hooks: Dict[str, Any]) -> Query:
    if "audit" in hooks:
        hooks["audit"](query, model, filters)
    if "metrics" in hooks:
        hooks["metrics"](query, model, filters)
    if "validation" in hooks:
        hooks["validation"](query, model, filters)
    return query

def filter_from_request(request: Request, model: Type[Base]) -> List[Dict[str, Union[str, Any]]]:
    spec = {}
    for key, value in request.query_params.items():
        col = getattr(model, key, None)
        if col is not None:
            spec[key] = {"op": "eq", "value": value}
    return [spec]

def filter_to_sql(filters: List[Dict[str, Union[str, Any]]], model: Type[Base]) -> str:
    clauses = []
    for f in filters:
        col = getattr(model, f["field"], None)
        if col is not None and OPS_EXTENDED.get(f.get("op", "eq")):
            clause = f"{f['field']} {OPS_EXTENDED[f['op']](col, f['value'])}"
            clauses.append(clause)
    return " AND ".join(clauses)


def _selftest() -> None:
    """Offline self-test: apply filter specs to a real SQLite query and assert the
    result set narrows correctly, and that unknown fields/ops are safely ignored."""
    from sqlalchemy import Integer, String, create_engine, select
    from sqlalchemy.orm import DeclarativeBase, Session, mapped_column

    class B(DeclarativeBase):
        pass

    class Product(B):
        __tablename__ = "filters_products"
        id = mapped_column(Integer, primary_key=True)
        name = mapped_column(String(50))
        category = mapped_column(String(20))
        price = mapped_column(Integer)

    engine = create_engine("sqlite://")
    B.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all([
            Product(id=1, name="apple", category="fruit", price=3),
            Product(id=2, name="banana", category="fruit", price=1),
            Product(id=3, name="carrot", category="veg", price=2),
            Product(id=4, name="daikon", category="veg", price=5),
        ])
        db.flush()

        # Equality filter narrows to the matching category.
        q = apply_filters(select(Product), Product, [{"field": "category", "op": "eq", "value": "fruit"}])
        rows = db.scalars(q).all()
        assert {r.id for r in rows} == {1, 2}, f"eq filter wrong: {[r.id for r in rows]}"

        # Range op narrows further and composes with a second filter.
        q2 = apply_filters(select(Product), Product,
                           [{"field": "category", "op": "eq", "value": "veg"},
                            {"field": "price", "op": "gte", "value": 3}])
        rows2 = db.scalars(q2).all()
        assert [r.id for r in rows2] == [4], f"composed filter wrong: {[r.id for r in rows2]}"

        # 'in' op.
        q3 = apply_filters(select(Product), Product, [{"field": "id", "op": "in", "value": [1, 3]}])
        assert {r.id for r in db.scalars(q3).all()} == {1, 3}

        # Negative/adversarial: an unknown column is ignored (no crash, no narrowing),
        # so injecting a bogus field cannot widen or error the query.
        q4 = apply_filters(select(Product), Product,
                           [{"field": "__import__", "op": "eq", "value": "os"}])
        assert len(db.scalars(q4).all()) == 4, "unknown field must be a no-op, not a filter/crash"

        # Negative: an unknown op is ignored rather than applied.
        q5 = apply_filters(select(Product), Product,
                           [{"field": "price", "op": "regex_delete", "value": 1}])
        assert len(db.scalars(q5).all()) == 4, "unknown op must be a no-op"

        # Policy enforcement rejects access to a non-permitted field.
        pol = FilterPolicy(field_permissions={"filters_products": ["category"]})
        try:
            apply_filters_with_policy(select(Product), Product,
                                      [{"field": "price", "op": "eq", "value": 1}], pol)
            raise AssertionError("policy did not block a forbidden field")
        except FilterFieldError:
            pass

    print("filters selftest: PASS")


if __name__ == "__main__":
    _selftest()
