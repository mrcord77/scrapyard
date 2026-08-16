"""
database — Database initialization + CRUD helpers for a generated application.

### PART-META-JSON
{
  "name": "database",
  "layer": "runtime",
  "purpose": "Runtime database wiring for generated apps: init_database (engine init, connectivity probe, dev create_all vs prod schema check, library security-table provisioning) plus ORM CRUD helpers (create/update/soft-or-hard delete/query/bulk ops) with per-model audit and policy hook registries and pydantic v2 serialization.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy",
    "pydantic"
  ],
  "inputs": "A settings object (database_url, dev flag), a declarative Base, ORM model classes, payload dicts.",
  "outputs": "A ready SQLAlchemy engine; persisted/updated ORM instances; serialized dicts.",
  "files_created": [],
  "security_notes": "In production (settings.dev False) init_database refuses to start when the schema or required security tables are missing instead of silently creating them, and connectivity failures fail fast at boot rather than mid-request. Policy hooks registered via policy_hook() run BEFORE mutations and abort them by raising PolicyViolation. Filter/sort keys are resolved via getattr on the model — pass only allow-listed field names, never raw user input. CRUD helpers commit; callers needing outer transaction control should use scrapyard.database.repository instead.",
  "ai_usage": "engine = init_database(settings, Base); then create_model(session, Model, data) etc. in route handlers.",
  "example": "engine = init_database(load_settings(), Base); create_model(session, Item, {'name': 'x'})",
  "import_path": "scrapyard.runtime.database"
}
### END-PART-META
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

STATUS = "core"

logger = logging.getLogger("scrapyard.runtime.database")


class DatabaseConnectionError(Exception):
    pass

class ModelNotFoundError(Exception):
    pass

class ValidationFailure(Exception):
    pass

class PolicyViolation(Exception):
    pass


# per-model hook registries: model -> (before, after) callables
_audit_hooks: Dict[type, Tuple[Optional[Callable], Optional[Callable]]] = {}
_policy_hooks: Dict[type, Tuple[Optional[Callable], Optional[Callable]]] = {}


def audit_hook(model_class: type, pre_commit: Optional[Callable] = None,
               post_commit: Optional[Callable] = None) -> None:
    """Register audit callables for a model: pre_commit(action, instance) runs
    before the commit, post_commit(action, instance) after a successful one."""
    _audit_hooks[model_class] = (pre_commit, post_commit)


def policy_hook(model_class: type, before: Optional[Callable] = None,
                after: Optional[Callable] = None) -> None:
    """Register policy callables for a model. ``before(action, instance_or_data)``
    may raise PolicyViolation to abort the mutation; ``after(action, instance)``
    runs post-commit."""
    _policy_hooks[model_class] = (before, after)


def clear_hooks() -> None:
    _audit_hooks.clear()
    _policy_hooks.clear()


def _run_before(model_class: type, action: str, payload: Any) -> None:
    before = _policy_hooks.get(model_class, (None, None))[0]
    if before is not None:
        before(action, payload)  # may raise PolicyViolation
    pre = _audit_hooks.get(model_class, (None, None))[0]
    if pre is not None:
        pre(action, payload)


def _run_after(model_class: type, action: str, instance: Any) -> None:
    post = _audit_hooks.get(model_class, (None, None))[1]
    if post is not None:
        post(action, instance)
    after = _policy_hooks.get(model_class, (None, None))[1]
    if after is not None:
        after(action, instance)


def create_model(session: Session, model_class: type, data: Dict[str, Any]) -> Any:
    try:
        _run_before(model_class, "create", data)
        instance = model_class(**data)
        session.add(instance)
        session.commit()
        _run_after(model_class, "create", instance)
        return instance
    except PolicyViolation:
        raise
    except TypeError as e:
        raise ValidationFailure(str(e)) from e
    except SQLAlchemyError as e:
        session.rollback()
        raise DatabaseConnectionError(f"Failed to create model: {e}") from e


def update_model(session: Session, model_class: type, model_id: int,
                 data: Dict[str, Any]) -> Any:
    try:
        instance = session.get(model_class, model_id)
        if not instance:
            raise ModelNotFoundError(f"No {model_class.__name__} found with id {model_id}")
        _run_before(model_class, "update", instance)
        for key, value in data.items():
            if not hasattr(model_class, key):
                raise ValidationFailure(f"Unknown field {key!r} for {model_class.__name__}")
            setattr(instance, key, value)
        session.commit()
        _run_after(model_class, "update", instance)
        return instance
    except (PolicyViolation, ModelNotFoundError, ValidationFailure):
        session.rollback()
        raise
    except SQLAlchemyError as e:
        session.rollback()
        raise DatabaseConnectionError(f"Failed to update model: {e}") from e


def delete_model(session: Session, model_class: type, model_id: int, soft: bool = True) -> None:
    try:
        instance = session.get(model_class, model_id)
        if not instance:
            raise ModelNotFoundError(f"No {model_class.__name__} found with id {model_id}")
        _run_before(model_class, "delete", instance)
        if soft:
            if not hasattr(instance, "is_deleted"):
                raise ValidationFailure(
                    f"{model_class.__name__} has no is_deleted column; use soft=False")
            setattr(instance, "is_deleted", True)
        else:
            session.delete(instance)
        session.commit()
        _run_after(model_class, "delete", instance)
    except (PolicyViolation, ModelNotFoundError, ValidationFailure):
        session.rollback()
        raise
    except SQLAlchemyError as e:
        session.rollback()
        raise DatabaseConnectionError(f"Failed to delete model: {e}") from e


def query_model(session: Session, model_class: type,
                filters: Optional[Dict[str, Any]] = None,
                sort: Optional[List[str]] = None,
                page: int = 1, per_page: int = 25) -> List[Any]:
    from sqlalchemy import select
    try:
        stmt = select(model_class)
        for key, value in (filters or {}).items():
            stmt = stmt.where(getattr(model_class, key) == value)
        for field_name in (sort or []):
            if field_name.startswith("-"):
                stmt = stmt.order_by(getattr(model_class, field_name[1:]).desc())
            else:
                stmt = stmt.order_by(getattr(model_class, field_name))
        stmt = stmt.offset((max(page, 1) - 1) * per_page).limit(per_page)
        return list(session.scalars(stmt).all())
    except SQLAlchemyError as e:
        raise DatabaseConnectionError(f"Failed to query model: {e}") from e


def bulk_create(session: Session, model_class: type, items: List[Dict[str, Any]]) -> List[Any]:
    try:
        for item in items:
            _run_before(model_class, "create", item)
        instances = [model_class(**item) for item in items]
        session.add_all(instances)
        session.commit()
        for instance in instances:
            _run_after(model_class, "create", instance)
        return instances
    except PolicyViolation:
        raise
    except TypeError as e:
        raise ValidationFailure(str(e)) from e
    except SQLAlchemyError as e:
        session.rollback()
        raise DatabaseConnectionError(f"Failed to bulk create models: {e}") from e


def bulk_update(session: Session, model_class: type, items: List[Dict[str, Any]]) -> List[Any]:
    """Each item must contain 'id' plus the fields to update. All ids must exist
    (the whole batch is rejected otherwise)."""
    try:
        pairs = []
        for item in items:
            if "id" not in item:
                raise ValidationFailure("each bulk_update item needs an 'id'")
            instance = session.get(model_class, item["id"])
            if instance is None:
                raise ModelNotFoundError(
                    f"No {model_class.__name__} found with id {item['id']}")
            pairs.append((instance, item))
        for instance, data in pairs:
            _run_before(model_class, "update", instance)
            for key, value in data.items():
                if key == "id":
                    continue
                if not hasattr(model_class, key):
                    raise ValidationFailure(f"Unknown field {key!r} for {model_class.__name__}")
                setattr(instance, key, value)
        session.commit()
        for instance, _ in pairs:
            _run_after(model_class, "update", instance)
        return [instance for instance, _ in pairs]
    except (PolicyViolation, ModelNotFoundError, ValidationFailure):
        session.rollback()
        raise
    except SQLAlchemyError as e:
        session.rollback()
        raise DatabaseConnectionError(f"Failed to bulk update models: {e}") from e


def serialize_model(model: Any, schema: type) -> Dict[str, Any]:
    """Serialize an ORM instance through a pydantic v2 schema class."""
    return schema.model_validate(model, from_attributes=True).model_dump()


def deserialize_model(model_class: type, data: Dict[str, Any]) -> Any:
    try:
        return model_class(**data)
    except TypeError as e:
        raise ValidationFailure(str(e)) from e


# --- grafted from original part (API stability) ---
def _ensure_security_tables(engine, security_caps, create: bool):
    """The generated routes write to library-owned tables (audit_logs, sessions)
    that live on a DIFFERENT declarative Base than the generated models. Their
    tables must exist too. Created individually (checkfirst) to avoid pulling in
    the library User/users table, which would collide with a domain User entity."""
    from sqlalchemy import inspect as sqla_inspect
    wanted = []
    if "audit_logs" in (security_caps or []):
        from scrapyard.admin.audit_logs import AuditLog
        wanted.append(AuditLog.__table__)
    if "session_manager" in (security_caps or []):
        from scrapyard.identity.session_manager import Session
        wanted.append(Session.__table__)
    if "users" in (security_caps or []):
        # library auth-principal table ('users'); the domain User entity is
        # collision-renamed to 'app_users', so these never clash.
        from scrapyard.identity.users import User as _AuthUser
        wanted.append(_AuthUser.__table__)
    if "roles" in (security_caps or []):
        # role-managed entities gate writes on user_roles; the table must exist.
        from scrapyard.authorization.roles import UserRole
        wanted.append(UserRole.__table__)
    if create:
        for t in wanted:
            t.create(engine, checkfirst=True)
    else:
        existing = set(sqla_inspect(engine).get_table_names())
        missing = [t.name for t in wanted if t.name not in existing]
        if missing:
            raise RuntimeError(
                f"security tables not initialized: {missing}. Run migrations before starting."
            )

def init_database(settings, base, *, create_tables: bool | None = None, security_caps=None):
    """Initialize the engine, verify connectivity, and ensure the schema is ready.

    Dev: creates generated tables AND the library security tables the routes use.
    Production: refuses to start if unreachable or the schema hasn't been applied.
    Returns the engine.
    """
    from sqlalchemy import inspect as sqla_inspect
    from scrapyard.database.db_session import init_engine
    engine = init_engine(settings.database_url)

    # connectivity probe — fail fast with a clear message instead of mid-request
    try:
        conn = engine.connect()
        conn.close()
    except Exception as e:
        raise RuntimeError(
            f"could not connect to database ({settings.database_url!r}): {e}"
        ) from e

    create = settings.dev if create_tables is None else create_tables
    if create:
        base.metadata.create_all(engine)
    else:
        existing = set(sqla_inspect(engine).get_table_names())
        missing = sorted(set(base.metadata.tables.keys()) - existing)
        if missing:
            raise RuntimeError(
                "database schema not initialized; missing tables: "
                f"{missing[:5]}{'...' if len(missing) > 5 else ''}. "
                "Run migrations before starting."
            )
    _ensure_security_tables(engine, security_caps, create)
    return engine


def _selftest() -> None:
    from dataclasses import dataclass

    from sqlalchemy import Boolean, Integer, String
    from sqlalchemy.orm import DeclarativeBase, Session as SASession, mapped_column, sessionmaker

    class Base(DeclarativeBase):
        pass

    class Widget(Base):
        __tablename__ = "runtime_db_widgets"
        id = mapped_column(Integer, primary_key=True)
        name = mapped_column(String(50))
        is_deleted = mapped_column(Boolean, default=False)

    @dataclass
    class _S:
        database_url: str = "sqlite://"
        dev: bool = True

    clear_hooks()

    # init_database: dev path creates tables and returns a live engine
    engine = init_database(_S(), Base, security_caps=None)
    with SASession(engine) as session:
        w = create_model(session, Widget, {"name": "one"})
        assert w.id is not None

        # unknown kwargs -> ValidationFailure (not a pydantic crash)
        try:
            create_model(session, Widget, {"name": "x", "bogus": 1})
            raise AssertionError("bad create accepted")
        except ValidationFailure:
            pass

        # update via session.get; unknown field rejected; missing id raises
        assert update_model(session, Widget, w.id, {"name": "one-b"}).name == "one-b"
        try:
            update_model(session, Widget, w.id, {"nope": 1})
            raise AssertionError("unknown update field accepted")
        except ValidationFailure:
            pass
        try:
            update_model(session, Widget, 999, {"name": "z"})
            raise AssertionError("missing id updated")
        except ModelNotFoundError:
            pass

        # bulk ops (the old bulk_update double-query/zip bug is gone)
        made = bulk_create(session, Widget, [{"name": "a"}, {"name": "b"}])
        assert len(made) == 2
        updated = bulk_update(session, Widget, [
            {"id": made[0].id, "name": "a2"}, {"id": made[1].id, "name": "b2"}])
        assert [u.name for u in updated] == ["a2", "b2"]
        try:
            bulk_update(session, Widget, [{"id": 12345, "name": "ghost"}])
            raise AssertionError("bulk_update accepted missing id")
        except ModelNotFoundError:
            pass

        # query with filters/sort/paging
        hits = query_model(session, Widget, filters={"name": "a2"})
        assert len(hits) == 1
        all_desc = query_model(session, Widget, sort=["-id"], per_page=2)
        assert len(all_desc) == 2 and all_desc[0].id > all_desc[1].id

        # soft + hard delete
        delete_model(session, Widget, w.id, soft=True)
        assert session.get(Widget, w.id).is_deleted is True
        delete_model(session, Widget, made[0].id, soft=False)
        assert session.get(Widget, made[0].id) is None

        # hooks are real: policy can veto, audit sees pre/post
        events: list = []
        audit_hook(Widget, pre_commit=lambda a, x: events.append(("pre", a)),
                   post_commit=lambda a, x: events.append(("post", a)))
        def no_deletes(action, payload):
            if action == "delete":
                raise PolicyViolation("deletes forbidden")
        policy_hook(Widget, before=no_deletes)
        w2 = create_model(session, Widget, {"name": "hooked"})
        assert ("pre", "create") in events and ("post", "create") in events
        try:
            delete_model(session, Widget, w2.id, soft=False)
            raise AssertionError("policy veto ignored")
        except PolicyViolation:
            pass
        assert session.get(Widget, w2.id) is not None
        clear_hooks()

        # serialization through a pydantic v2 schema
        from pydantic import BaseModel

        class WidgetOut(BaseModel):
            id: int
            name: str

        blob = serialize_model(w2, WidgetOut)
        assert blob == {"id": w2.id, "name": "hooked"}
        assert deserialize_model(Widget, {"name": "fresh"}).name == "fresh"
        try:
            deserialize_model(Widget, {"bogus": 1})
            raise AssertionError("bad deserialize accepted")
        except ValidationFailure:
            pass

    # non-dev with missing schema refuses to start
    class OtherBase(DeclarativeBase):
        pass

    class Missing(OtherBase):
        __tablename__ = "runtime_db_missing"
        id = mapped_column(Integer, primary_key=True)

    try:
        init_database(_S(dev=False), OtherBase)
        raise AssertionError("prod path created tables silently")
    except RuntimeError as e:
        assert "not initialized" in str(e)

    print("runtime.database selftest: PASS")


if __name__ == "__main__":
    _selftest()

