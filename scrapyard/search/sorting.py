"""
sorting — Whitelisted multi-field sorting for SQLAlchemy queries from user-supplied
sort tokens ('field' / '-field'), with policy hooks and serialization helpers.

### PART-META-JSON
{
  "name": "sorting",
  "layer": "search",
  "purpose": "Turns user-supplied sort tokens (['name', '-created']) into SQLAlchemy order_by clauses safely: SortConfig whitelists sortable fields (strict mode raises SortError on unknown fields, lenient mode drops them), SortPolicy hooks per-field authorization, apply_sort/apply_sort_with_policy/apply_sort_with_config attach ordering to Query or Select objects, and (de)serializers round-trip sort state through query strings.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy",
    "pydantic"
  ],
  "inputs": "User sort token lists ('field' ascending, '-field' descending), a SortConfig whitelist, SQLAlchemy Query/Select objects and mapped model classes.",
  "outputs": "Validated token lists, Query/Select objects with order_by applied, comma-joined serialized sort strings.",
  "files_created": [],
  "security_notes": "This part exists to stop sort-parameter injection: field names are resolved ONLY against the model via getattr after whitelist validation, so raw user strings never reach SQL. Two failure modes to respect: (1) always populate SortConfig.allowed_fields from get_sortable_fields or a hand-picked subset - an empty whitelist with enforce_whitelist=False silently ignores all sorting; (2) sorting by a sensitive column (e.g. salary) leaks ordering information even when the column itself is not returned, so whitelist deliberately. No network, file, or secret handling.",
  "ai_usage": "config = SortConfig(allowed_fields=['id','name']); tokens = build_sort(user_tokens, config); query = apply_sort(query, Model, tokens). Use enforce_whitelist=False to drop instead of raise.",
  "example": "from scrapyard.search.sorting import SortConfig, build_sort, apply_sort",
  "import_path": "scrapyard.search.sorting"
}
### END-PART-META
"""
from typing import Any, Iterator, List, Optional

from pydantic import BaseModel


class SortConfig(BaseModel):
    allowed_fields: List[str]
    default_direction: str = 'asc'
    enforce_whitelist: bool = True


class SortError(Exception):
    pass


def validate_sort_tokens(tokens: List[str], config: SortConfig) -> List[str]:
    """Validate user sort tokens against the whitelist.

    Strict mode (enforce_whitelist=True) raises SortError on unknown fields;
    lenient mode silently drops them.
    """
    valid_tokens: List[str] = []
    for token in tokens:
        field_name = token[1:] if token.startswith('-') else token
        if field_name not in config.allowed_fields:
            if config.enforce_whitelist:
                raise SortError(f"Unknown field: {field_name}")
            continue  # lenient: drop unknown fields
        valid_tokens.append(token)
    return valid_tokens


def build_sort(user_sort: Optional[List[str]], config: SortConfig) -> List[str]:
    """Build a validated sort token list from raw user input (None -> [])."""
    if user_sort is None:
        return []
    return validate_sort_tokens(user_sort, config)


class SortPolicy:
    """Per-field sort authorization hook; override apply() for real policies."""

    def apply(self, field: str, user: Optional[Any]) -> bool:
        return True


def apply_sort(query, model, sort: Optional[List[str]]):
    """Apply sort tokens to a Query/Select. sort: ['field', '-other'] where a
    leading '-' means descending. Unknown fields are ignored so user input
    can't break the query (pair with build_sort for strict validation)."""
    for token in (sort or []):
        descending = token.startswith("-")
        name = token[1:] if descending else token
        col = getattr(model, name, None)
        if col is not None:
            query = query.order_by(col.desc() if descending else col.asc())
    return query


def apply_sort_with_policy(query, model, sort: Optional[List[str]],
                           policy: SortPolicy, user: Optional[Any] = None):
    """Like apply_sort but consults the policy per field before ordering."""
    for token in (sort or []):
        descending = token.startswith("-")
        name = token[1:] if descending else token
        col = getattr(model, name, None)
        if col is not None and policy.apply(name, user):
            query = query.order_by(col.desc() if descending else col.asc())
    return query


def get_sortable_fields(model) -> List[str]:
    """All mapped column names of a SQLAlchemy model."""
    return [column.key for column in model.__mapper__.columns]


def apply_sort_with_config(query, model, sort: Optional[List[str]],
                           config: SortConfig, policy: Optional[SortPolicy] = None):
    """Validate tokens against config, then apply them (optionally via policy)."""
    tokens = build_sort(sort, config)
    return apply_sort_with_policy(query, model, tokens, policy or SortPolicy())


def bulk_sort(queries: List[Any], models: List[type],
              sort: Optional[List[str]]) -> Iterator[Any]:
    """Apply the same sort tokens across parallel (query, model) pairs.

    Each model's own sortable fields form its whitelist (lenient mode, so a
    token missing on one model is dropped only for that model).
    """
    for query, model in zip(queries, models):
        config = SortConfig(allowed_fields=get_sortable_fields(model),
                            enforce_whitelist=False)
        yield apply_sort_with_config(query, model, sort, config)


def sort_serializer(sort: List[str]) -> str:
    return ','.join(sort)


def sort_deserializer(serialized: str) -> List[str]:
    return [t for t in serialized.split(',') if t]


def _selftest() -> None:
    """Offline selftest with an in-memory SQLite model."""
    from sqlalchemy import Integer, String, create_engine, select
    from sqlalchemy.orm import (DeclarativeBase, Mapped, Session,
                                mapped_column)

    class _Base(DeclarativeBase):
        pass

    class Person(_Base):
        __tablename__ = "sorting_selftest_people"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        name: Mapped[str] = mapped_column(String(50))
        age: Mapped[int] = mapped_column(Integer)

    # Token validation: strict raises, lenient drops
    config = SortConfig(allowed_fields=["id", "name"])
    assert build_sort(["name", "-id"], config) == ["name", "-id"]
    assert build_sort(None, config) == []
    try:
        build_sort(["-age"], config)
        raise AssertionError("strict mode must raise on unknown field")
    except SortError:
        pass
    lenient = SortConfig(allowed_fields=["id", "name"], enforce_whitelist=False)
    assert build_sort(["-age", "name"], lenient) == ["name"]

    # Introspection
    assert get_sortable_fields(Person) == ["id", "name", "age"]

    # Serialization round-trip
    assert sort_deserializer(sort_serializer(["a", "-b"])) == ["a", "-b"]
    assert sort_deserializer("") == []

    engine = create_engine("sqlite:///:memory:")
    try:
        _Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add_all([
                Person(name="Carol", age=30),
                Person(name="Alice", age=40),
                Person(name="Bob", age=40),
            ])
            session.commit()

            # apply_sort on a Select: ascending
            stmt = apply_sort(select(Person), Person, ["name"])
            names = [p.name for p in session.scalars(stmt)]
            assert names == ["Alice", "Bob", "Carol"], names

            # descending + multi-field
            stmt = apply_sort(select(Person), Person, ["-age", "name"])
            rows = [(p.age, p.name) for p in session.scalars(stmt)]
            assert rows == [(40, "Alice"), (40, "Bob"), (30, "Carol")], rows

            # unknown field ignored, query still runs
            stmt = apply_sort(select(Person), Person, ["nope", "name"])
            names = [p.name for p in session.scalars(stmt)]
            assert names == ["Alice", "Bob", "Carol"]

            # legacy Query API works too
            q = apply_sort(session.query(Person), Person, ["-name"])
            assert [p.name for p in q.all()] == ["Carol", "Bob", "Alice"]

            # policy vetoes a field
            class DenyAge(SortPolicy):
                def apply(self, field, user):
                    return field != "age"

            stmt = apply_sort_with_policy(select(Person), Person,
                                          ["-age", "name"], DenyAge())
            names = [p.name for p in session.scalars(stmt)]
            assert names == ["Alice", "Bob", "Carol"]  # only name applied

            # config + policy combined
            full = SortConfig(allowed_fields=get_sortable_fields(Person))
            stmt = apply_sort_with_config(select(Person), Person, ["-id"], full)
            ids = [p.id for p in session.scalars(stmt)]
            assert ids == sorted(ids, reverse=True)

            # bulk_sort over parallel queries
            results = list(bulk_sort([select(Person), select(Person)],
                                     [Person, Person], ["name"]))
            assert len(results) == 2
            for stmt in results:
                assert [p.name for p in session.scalars(stmt)] == \
                    ["Alice", "Bob", "Carol"]
    finally:
        engine.dispose()

    print("sorting selftest: all tests passed")


if __name__ == '__main__':
    _selftest()
