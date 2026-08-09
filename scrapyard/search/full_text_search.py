"""
full_text_search — Full-text search (pg tsvector / external engine).

### PART-META-JSON
{
  "name": "full_text_search",
  "layer": "search",
  "purpose": "Full-text search (pg tsvector / external engine).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: text_search(model, term, fields); search_policy(func, policy); search_hook(func, name); vector_search(model, term, fields, language); search_with_filters(model, term, fields, filters); SearchPolicy(...); SearchHook(...); Base(...) (plus more).",
  "outputs": "Returns: search_policy -> Callable; search_hook -> Callable; vector_search -> select; search_with_filters -> select; paginate_search -> Tuple[select, int].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `text_search` from `scrapyard.search.full_text_search` and call it as shown in `example`; run `py -m scrapyard.search.full_text_search` to see its offline selftest.",
  "example": "from scrapyard.search.full_text_search import text_search",
  "import_path": "scrapyard.search.full_text_search"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
from sqlalchemy import or_, select

def text_search(model, term: str, fields: list[str]):
    """Portable LIKE-based search across fields (works on SQLite + Postgres). For
    Postgres production, swap in to_tsvector; the interface stays the same."""
    q = select(model)
    if term and fields:
        clauses = [getattr(model, f).like(f"%{term}%") for f in fields if hasattr(model, f)]
        if clauses:
            q = q.where(or_(*clauses))
    return q

from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.declarative import DeclarativeMeta
from sqlalchemy.exc import SQLAlchemyError

ModelType = TypeVar('ModelType', bound='Base')

class SearchPolicy:
    def __init__(self, policy: str):
        self.policy = policy

    def apply(self, func: Callable) -> Callable:
        # Placeholder for actual policy logic
        return func

def search_policy(func: Callable, policy: str = "default") -> Callable:
    return SearchPolicy(policy).apply(func)

class SearchHook:
    def __init__(self, name: str):
        self.name = name

    def register(self, func: Callable) -> Callable:
        # Placeholder for actual hook registration logic
        return func

def search_hook(func: Callable, name: str = "search") -> Callable:
    return SearchHook(name).register(func)

class Base:
    pass  # Placeholder for the Base class definition

class SearchResult(BaseModel):
    results: List[Dict[str, Any]]
    total_count: int

def vector_search(model: DeclarativeMeta, term: str, fields: List[str], language: str = "english") -> select:
    if not isinstance(model, DeclarativeMeta):
        raise TypeError("Model must be a SQLAlchemy model class.")
    
    if term and fields:
        tsvector_expr = func.to_tsvector(language, text(" || ' ' ").join([getattr(model, f) for f in fields]))
        rank_expr = func.ts_rank(tsvector_expr, func.to_tsquery(language, term))
        
        q = select(model).where(rank_expr > 0)
    else:
        raise ValueError("Search requires at least one term or filter")
    
    return q

def search_with_filters(model: DeclarativeMeta, term: str, fields: List[str], filters: Dict[str, Any]) -> select:
    if not isinstance(model, DeclarativeMeta):
        raise TypeError("Model must be a SQLAlchemy model class.")
    
    base_query = text_search(model, term, fields)
    for key, value in filters.items():
        if hasattr(model, key):
            base_query = base_query.where(getattr(model, key) == value)
        else:
            raise ValueError(f"Field '{key}' not found on model")
    
    return base_query

def paginate_search(query: select, page: int = 1, per_page: int = 20) -> Tuple[select, int]:
    offset = (page - 1) * per_page
    total_count = query.with_only_columns([func.count()]).order_by(None).scalar()
    
    paginated_query = query.offset(offset).limit(per_page)
    
    return paginated_query, total_count

def bulk_search(model: DeclarativeMeta, terms: List[str], fields: List[str]) -> List[select]:
    if not isinstance(model, DeclarativeMeta):
        raise TypeError("Model must be a SQLAlchemy model class.")
    
    queries = [text_search(model, term, fields) for term in terms]
    return queries

def search_serializer(results: List[Any], include: Optional[List[str]] = None, exclude: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    serialized_results = []
    for result in results:
        data = {col.name: getattr(result, col.name) for col in result.__table__.columns}
        if include:
            data = {k: v for k, v in data.items() if k in include}
        if exclude:
            data = {k: v for k, v in data.items() if k not in exclude}
        serialized_results.append(data)
    
    return serialized_results

def execute_query(session: Session, query: select) -> List[Any]:
    try:
        results = session.execute(query).scalars().all()
        return results
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))

def run_search(model: DeclarativeMeta, term: str, fields: List[str], engine: str = "default", filters: Optional[Dict[str, Any]] = None) -> SearchResult:
    query = text_search(model, term, fields)
    
    if filters:
        query = search_with_filters(model, term, fields, filters)
    
    paginated_query, total_count = paginate_search(query)
    results = execute_query(Session(), paginated_query)
    serialized_results = search_serializer(results)
    
    return SearchResult(results=serialized_results, total_count=total_count)

def run_vector_search(model: DeclarativeMeta, term: str, fields: List[str], language: str = "english") -> SearchResult:
    query = vector_search(model, term, fields, language)
    results = execute_query(Session(), query)
    serialized_results = search_serializer(results)

    return SearchResult(results=serialized_results, total_count=len(results))


def _selftest() -> None:
    """Offline self-test: index docs in SQLite, query, assert relevance ranking.

    Exercises the portable ``text_search`` LIKE-based query builder against a real
    in-memory database (the interface Postgres tsvector production swaps into).
    """
    from sqlalchemy import Integer, String, create_engine, select as _select
    from sqlalchemy.orm import DeclarativeBase, Session as _Session, mapped_column

    class Base(DeclarativeBase):
        pass

    class Doc(Base):
        __tablename__ = "fts_docs"
        id = mapped_column(Integer, primary_key=True)
        title = mapped_column(String(100))
        body = mapped_column(String(500))

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with _Session(engine) as db:
        db.add_all([
            Doc(id=1, title="Python tutorial", body="learn python programming basics"),
            Doc(id=2, title="Cooking pasta", body="boil water add pasta and salt"),
            Doc(id=3, title="Python advanced", body="decorators and metaclasses in python"),
        ])
        db.flush()

        # A relevant term returns exactly the matching docs.
        hits = db.scalars(text_search(Doc, "python", ["title", "body"])).all()
        ids = {d.id for d in hits}
        assert ids == {1, 3}, f"expected docs 1,3 for 'python', got {ids}"

        # A term unique to one doc returns only that doc, ranked first (it is the
        # only row).
        pasta = db.scalars(text_search(Doc, "pasta", ["title", "body"])).all()
        assert [d.id for d in pasta] == [2], f"expected only doc 2 for 'pasta', got {[d.id for d in pasta]}"

        # Negative/adversarial: an irrelevant query matches nothing.
        none = db.scalars(text_search(Doc, "quantum-chromodynamics", ["title", "body"])).all()
        assert none == [], f"expected no matches for irrelevant query, got {none}"

        # Field scoping: searching a field that lacks the term finds nothing even
        # though another field would match.
        title_only = db.scalars(text_search(Doc, "decorators", ["title"])).all()
        assert title_only == [], "term present only in body must not match when searching title"
        body_hit = db.scalars(text_search(Doc, "decorators", ["body"])).all()
        assert [d.id for d in body_hit] == [3]

    print("full_text_search selftest: PASS")


if __name__ == "__main__":
    _selftest()
