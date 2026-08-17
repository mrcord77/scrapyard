"""
repository — Generic typed repository over a model.

### PART-META-JSON
{
  "name": "repository",
  "layer": "database",
  "purpose": "Generic CRUD repository over a SQLAlchemy 2.x model + session: get/list/add/delete/count, create/update/bulk ops that accept dicts, pydantic models, or ORM instances, filtering and sorting, column-based serialization, plus pluggable audit-log, policy-check, and metrics hooks.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "A SQLAlchemy declarative model class and an active Session; entity payloads as dicts, pydantic models, or ORM instances.",
  "outputs": "ORM instances (flushed, not committed — transaction control stays with the caller).",
  "files_created": [],
  "security_notes": "Payload dicts are validated against the model's mapped columns; unknown keys raise ValidationError instead of being silently dropped, and primary-key/_sa_instance_state attributes are never copied during updates. filter()/sort fields are resolved via getattr on the model and raise on unknown attributes, so callers must not pass raw user input as field names without an allow-list. The audit hook receives entity primary keys, not full row contents.",
  "ai_usage": "repo = Repository(User, session); repo.create({'name': 'x'}); repo.update(1, {'name': 'y'}); repo.filter(filters={'name': 'y'}).",
  "example": "repo = Repository(User, session); user = repo.create({'email': 'a@b.c'})",
  "import_path": "scrapyard.database.repository"
}
### END-PART-META
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Generic, List, Optional, Type, TypeVar

STATUS = "core"

T = TypeVar("T")

logger = logging.getLogger("scrapyard.database.repository")


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


class BulkOperationError(Exception):
    """Raised on partial failure in bulk_create or bulk_delete."""
    pass


class SerializationError(Exception):
    """Raised when serialization fails."""
    pass


class Repository(Generic[T]):
    """Generic CRUD repository over a SQLAlchemy model + session.

    create/update/bulk_create accept three payload shapes:
    - dict of column values
    - pydantic model (v2: model_dump() is used)
    - an ORM instance of the repository's model (used as-is)
    """

    def __init__(self, model: Type[T], db) -> None:
        self.model = model
        self.db = db
        self._audit_hook: Optional[Callable[[str, Any, str], None]] = None
        self._policy_hook: Optional[Callable[[str, str, Optional[T]], bool]] = None
        self._metrics: Dict[str, Dict[str, int]] = {}

    # --- introspection helpers -------------------------------------------

    def _column_names(self) -> set[str]:
        from sqlalchemy import inspect
        return {attr.key for attr in inspect(self.model).mapper.column_attrs}

    def _pk_names(self) -> set[str]:
        from sqlalchemy import inspect
        mapper = inspect(self.model).mapper
        return {mapper.get_property_by_column(col).key for col in mapper.primary_key}

    def _extract_data(self, obj: Any) -> Dict[str, Any]:
        """Normalise dict / pydantic model / ORM instance into a column dict."""
        if isinstance(obj, dict):
            data = dict(obj)
        elif isinstance(obj, self.model):
            cols = self._column_names()
            data = {k: getattr(obj, k) for k in cols}
        elif hasattr(obj, "model_dump"):  # pydantic v2 model
            data = obj.model_dump(exclude_unset=True)
        else:
            raise ValidationError(
                f"Unsupported payload type {type(obj).__name__}; "
                f"expected dict, pydantic model, or {self.model.__name__} instance")
        unknown = set(data) - self._column_names()
        if unknown:
            raise ValidationError(f"Unknown fields for {self.model.__name__}: {sorted(unknown)}")
        return data

    # --- basic CRUD -------------------------------------------------------

    def get(self, id_: object) -> T | None:
        return self.db.get(self.model, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        from sqlalchemy import select
        return self.db.scalars(select(self.model).limit(limit).offset(offset)).all()

    def add(self, obj: T) -> T:
        self.db.add(obj)
        self.db.flush()
        return obj

    def delete(self, obj: T) -> None:
        self.db.delete(obj)
        self.db.flush()

    def count(self) -> int:
        from sqlalchemy import func, select
        return self.db.scalar(select(func.count()).select_from(self.model)) or 0

    def create(self, obj: T | Dict[str, Any]) -> T:
        """Create from a dict, pydantic model, or ORM instance."""
        try:
            entity = self.validate(obj)
            self.db.add(entity)
            self.db.flush()
            self.audit_log("create", entity, "system")
            self.metrics_track("create", True)
            return entity
        except ValidationError:
            self.metrics_track("create", False)
            raise
        except Exception as e:
            self.metrics_track("create", False)
            logger.error("Failed to create %s: %s", self.model.__name__, e)
            raise

    def update(self, id_: object, obj: T | Dict[str, Any]) -> T | None:
        """Update entity ``id_`` from a dict, pydantic model, or ORM instance.

        Only mapped column attributes are copied; primary keys and SQLAlchemy
        instance state are never overwritten.
        """
        try:
            existing = self.get(id_)
            if not existing:
                return None
            data = self._extract_data(obj)
            pks = self._pk_names()
            for key, value in data.items():
                if key in pks:
                    continue
                setattr(existing, key, value)
            self.db.flush()
            self.audit_log("update", existing, "system")
            self.metrics_track("update", True)
            return existing
        except ValidationError:
            self.metrics_track("update", False)
            raise
        except Exception as e:
            self.metrics_track("update", False)
            logger.error("Failed to update %s id=%r: %s", self.model.__name__, id_, e)
            raise

    def delete_by_id(self, id_: object) -> T | None:
        try:
            obj = self.get(id_)
            if not obj:
                return None
            self.db.delete(obj)
            self.db.flush()
            self.audit_log("delete", obj, "system")
            self.metrics_track("delete", True)
            return obj
        except Exception as e:
            self.metrics_track("delete", False)
            logger.error("Failed to delete %s id=%r: %s", self.model.__name__, id_, e)
            raise

    def filter(self, *, filters: Optional[Dict[str, Any]] = None,
               sort: Optional[List[str]] = None,
               limit: int = 50, offset: int = 0) -> List[T]:
        from sqlalchemy import select
        query = select(self.model)
        if filters:
            for key, value in filters.items():
                query = query.where(getattr(self.model, key) == value)
        if sort:
            for field in sort:
                if field.startswith("-"):
                    query = query.order_by(getattr(self.model, field[1:]).desc())
                else:
                    query = query.order_by(getattr(self.model, field))
        return self.db.scalars(query.limit(limit).offset(offset)).all()

    def bulk_create(self, objs: List[T | Dict[str, Any]]) -> List[T]:
        try:
            entities = [self.validate(obj) for obj in objs]
        except ValidationError:
            self.metrics_track("bulk_create", False)
            raise
        try:
            self.db.add_all(entities)
            self.db.flush()
            for entity in entities:
                self.audit_log("create", entity, "system")
            self.metrics_track("bulk_create", True)
            return entities
        except Exception as e:
            self.metrics_track("bulk_create", False)
            logger.error("Failed to bulk create %s: %s", self.model.__name__, e)
            raise BulkOperationError(e) from e

    def bulk_delete(self, ids: List[object]) -> List[T]:
        try:
            deleted: List[T] = []
            for id_ in ids:
                obj = self.get(id_)
                if not obj:
                    continue
                self.db.delete(obj)
                self.db.flush()
                deleted.append(obj)
            for obj in deleted:
                self.audit_log("delete", obj, "system")
            self.metrics_track("bulk_delete", True)
            return deleted
        except Exception as e:
            self.metrics_track("bulk_delete", False)
            logger.error("Failed to bulk delete %s: %s", self.model.__name__, e)
            raise

    # --- serialization / validation --------------------------------------

    def serialize(self, obj: T) -> Dict[str, Any]:
        """Serialize an ORM instance to a plain dict of its mapped columns."""
        try:
            return {k: getattr(obj, k) for k in self._column_names()}
        except Exception as e:
            logger.error("Failed to serialize %s: %s", type(obj).__name__, e)
            raise SerializationError(e) from e

    def validate(self, obj: T | Dict[str, Any]) -> T:
        """Return an ORM instance for the payload.

        - ORM instance of self.model: returned unchanged (NOT re-constructed).
        - dict / pydantic model: keys checked against mapped columns, then a
          new instance is constructed.
        """
        if isinstance(obj, self.model):
            return obj
        data = self._extract_data(obj)
        try:
            return self.model(**data)
        except TypeError as e:
            raise ValidationError(str(e)) from e

    # --- hooks -------------------------------------------------------------

    def set_audit_hook(self, hook: Callable[[str, Any, str], None]) -> None:
        """Register callable(action, pk_dict, user) fired after each mutation."""
        self._audit_hook = hook

    def audit_log(self, action: str, obj: T, user: str) -> None:
        """Structured audit record: action + primary key values + user."""
        try:
            pks = {k: getattr(obj, k, None) for k in self._pk_names()}
        except Exception:
            pks = {}
        logger.info("repo_audit model=%s action=%s pk=%s user=%s",
                    self.model.__name__, action, pks, user,
                    extra={"audit": {"model": self.model.__name__, "action": action,
                                     "pk": pks, "user": user}})
        if self._audit_hook is not None:
            self._audit_hook(action, pks, user)

    def set_policy_hook(self, hook: Callable[[str, str, Optional[T]], bool]) -> None:
        """Register callable(user, action, obj) -> bool consulted by policy_check."""
        self._policy_hook = hook

    def policy_check(self, user: str, action: str, obj: Optional[T] = None) -> bool:
        """True if ``user`` may perform ``action``. Default allow; register a
        policy hook to enforce real rules."""
        if self._policy_hook is not None:
            return bool(self._policy_hook(user, action, obj))
        return True

    def metrics_track(self, action: str, success: bool) -> None:
        """Count per-action success/failure; read back via get_metrics()."""
        bucket = self._metrics.setdefault(action, {"success": 0, "failure": 0})
        bucket["success" if success else "failure"] += 1

    def get_metrics(self) -> Dict[str, Dict[str, int]]:
        return {k: dict(v) for k, v in self._metrics.items()}


def _selftest() -> None:
    from sqlalchemy import Integer, String, create_engine
    from sqlalchemy.orm import DeclarativeBase, Session, mapped_column

    class Base(DeclarativeBase):
        pass

    class Item(Base):
        __tablename__ = "repository_items"
        id = mapped_column(Integer, primary_key=True)
        name = mapped_column(String(50))
        qty = mapped_column(Integer, default=0)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo: Repository[Item] = Repository(Item, session)

        # create from dict
        a = repo.create({"name": "alpha", "qty": 1})
        assert a.id is not None and a.name == "alpha"

        # create from ORM instance (used to explode via self.model(**instance))
        b = repo.create(Item(name="beta", qty=2))
        assert isinstance(b, Item) and b.id is not None

        # create from a pydantic model
        from pydantic import BaseModel

        class ItemIn(BaseModel):
            name: str
            qty: int = 0

        c = repo.create(ItemIn(name="gamma", qty=3))
        assert c.name == "gamma"

        # unknown fields rejected, not silently dropped
        try:
            repo.create({"name": "bad", "nope": 1})
            raise AssertionError("unknown field accepted")
        except ValidationError:
            pass

        # update from dict; pk not clobbered
        updated = repo.update(a.id, {"qty": 42, "id": 999})
        assert updated is not None and updated.qty == 42 and updated.id == a.id
        # update from ORM instance must not copy _sa_instance_state
        donor = Item(name="beta2", qty=20)
        updated_b = repo.update(b.id, donor)
        assert updated_b is b and b.name == "beta2" and b.qty == 20
        assert repo.get(b.id).name == "beta2"
        # update of missing id
        assert repo.update(10_000, {"qty": 0}) is None

        # bulk create mixed shapes
        made = repo.bulk_create([{"name": "d1"}, Item(name="d2", qty=9)])
        assert len(made) == 2 and all(m.id is not None for m in made)
        try:
            repo.bulk_create([{"name": "x", "bogus": True}])
            raise AssertionError("bulk_create accepted unknown field")
        except ValidationError:
            pass

        # list/filter/sort/count
        assert repo.count() == 5
        assert len(repo.list(limit=2)) == 2
        hits = repo.filter(filters={"name": "gamma"})
        assert len(hits) == 1 and hits[0].qty == 3
        ordered = repo.filter(sort=["-qty"], limit=1)
        assert ordered[0].qty == 42

        # serialize returns plain column dict, no _sa_instance_state
        blob = repo.serialize(a)
        assert blob["name"] == "alpha" and "_sa_instance_state" not in blob

        # delete paths
        gone = repo.delete_by_id(c.id)
        assert gone is c and repo.get(c.id) is None
        assert repo.delete_by_id(c.id) is None
        deleted = repo.bulk_delete([m.id for m in made] + [12345])
        assert len(deleted) == 2
        assert repo.count() == 2

        # hooks: audit, policy, metrics
        audits: list = []
        repo.set_audit_hook(lambda action, pk, user: audits.append((action, pk, user)))
        repo.create({"name": "audited"})
        assert audits and audits[-1][0] == "create" and audits[-1][2] == "system"
        assert repo.policy_check("anyone", "create") is True
        repo.set_policy_hook(lambda user, action, obj: user == "admin")
        assert repo.policy_check("admin", "delete") and not repo.policy_check("bob", "delete")
        metrics = repo.get_metrics()
        assert metrics["create"]["success"] >= 4 and metrics["create"]["failure"] >= 1

    print("repository selftest: PASS")


if __name__ == "__main__":
    _selftest()
