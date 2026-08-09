"""
factories — Model factories/fixtures for tests.

### PART-META-JSON
{
  "name": "factories",
  "layer": "testing",
  "purpose": "Model factories/fixtures for tests.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: reset_counter(); make_user(db, **overrides); build_model(model, **fields); create_model(db, model, **overrides); bulk_create(db, model, instances, batch_size); ModelNotFoundError(...); InvalidFieldError(...); FactoryPolicyViolation(...) (plus more).",
  "outputs": "Returns: make_user -> MappedAsDataclass; build_model -> MappedAsDataclass; create_model -> MappedAsDataclass; bulk_create -> None; apply_policy -> bool.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `reset_counter` from `scrapyard.testing.factories` and call it as shown in `example`; run `py -m scrapyard.testing.factories` to see its offline selftest.",
  "example": "from scrapyard.testing.factories import reset_counter",
  "import_path": "scrapyard.testing.factories"
}
### END-PART-META
"""
from __future__ import annotations
import itertools
from typing import Any, Dict, List, Type
from sqlalchemy.orm import Session, MappedAsDataclass, Mapped
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError
from fastapi.encoders import jsonable_encoder
import logging

STATUS = "core"

_counter = itertools.count(1)
_logger = logging.getLogger(__name__)

class ModelNotFoundError(Exception):
    pass

class InvalidFieldError(Exception):
    pass

class FactoryPolicyViolation(Exception):
    pass

class BulkCreateError(Exception):
    pass

class SerializationError(Exception):
    pass

class AuditLogFailure(Exception):
    pass

class ConfigMissingError(Exception):
    pass

FACTORY_DEFAULT_DOMAIN = "example.test"
FACTORY_DEFAULT_PASSWORD = "password123"
FACTORY_AUDIT_LOG_ENABLED = False
FACTORY_POLICY_MODULE = "scrapyard.testing.policies"
FACTORY_MAX_BULK_SIZE = 100
FACTORY_SERIALIZE_DEPTH = 2
FACTORY_USE_COUNTER = True

def reset_counter():
    global _counter
    _counter = itertools.count(1)

def make_user(db: Session, **overrides) -> MappedAsDataclass:
    from scrapyard.identity.users import UserService
    n = next(_counter)
    email = overrides.pop("email", f"user{n}@{FACTORY_DEFAULT_DOMAIN}")
    password = overrides.pop("password", FACTORY_DEFAULT_PASSWORD)
    u = UserService(db).create(email, password)
    for k, v in overrides.items():
        setattr(u, k, v)
    db.flush()
    return u

def build_model(model: Type[MappedAsDataclass], **fields) -> MappedAsDataclass:
    try:
        instance = model(**fields)
        if FACTORY_AUDIT_LOG_ENABLED:
            _logger.info(f"Built {model.__name__} with fields: {fields}")
        return instance
    except (ValidationError, TypeError) as e:
        raise InvalidFieldError(str(e)) from e

def create_model(db: Session, model: Type[MappedAsDataclass], **overrides) -> MappedAsDataclass:
    try:
        if FACTORY_POLICY_MODULE:
            import_policy_module(FACTORY_POLICY_MODULE)
        instance = build_model(model, **overrides)
        db.add(instance)
        db.flush()
        _logger.info(f"Created {model.__name__} with fields: {overrides}")
        return instance
    except Exception as e:
        raise FactoryPolicyViolation(str(e)) from e

def bulk_create(db: Session, model: Type[MappedAsDataclass], instances: List[Dict[str, Any]], batch_size: int = FACTORY_MAX_BULK_SIZE) -> None:
    if not isinstance(instances, list):
        raise TypeError("Instances must be a list of dictionaries")
    
    for i in range(0, len(instances), batch_size):
        batch = instances[i:i + batch_size]
        try:
            with db.begin():
                for instance_data in batch:
                    create_model(db, model, **instance_data)
        except IntegrityError as e:
            raise BulkCreateError(str(e)) from e

def apply_policy(policy_module: str) -> bool:
    try:
        __import__(policy_module)
        return True
    except ImportError:
        _logger.warning(f"Policy module {policy_module} not found")
        return False

def with_relations(db: Session, model: Type[MappedAsDataclass], **relations):
    
    instance = create_model(db, model, **relations)
    for relation_name, relation_instance in relations.items():
        if isinstance(relation_instance, MappedAsDataclass):
            setattr(instance, relation_name, relation_instance)
            db.flush()
    
    return instance

def generate_unique_field(field_type: Type[Mapped], field_name: str) -> str:
    while True:
        unique_value = f"unique_{field_name}_{next(_counter)}"
        return unique_value

def _prune_depth(value: Any, depth: int) -> Any:
    """Trim nested containers deeper than `depth` (replaced with None)."""
    if depth < 0:
        return None
    if isinstance(value, dict):
        return {k: _prune_depth(v, depth - 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_prune_depth(v, depth - 1) for v in value]
    return value

def serialize_model(instance: MappedAsDataclass, depth: int = FACTORY_SERIALIZE_DEPTH) -> Dict[str, Any]:
    """jsonable_encoder has no max_recursion kwarg (fixed); depth limiting is
    applied by pruning the encoded structure."""
    try:
        encoded = jsonable_encoder(instance)
        return _prune_depth(encoded, depth)
    except Exception as e:
        raise SerializationError(str(e)) from e

# The tunable factory settings configure_factory may change.
_CONFIGURABLE = {
    "FACTORY_DEFAULT_DOMAIN", "FACTORY_DEFAULT_PASSWORD", "FACTORY_AUDIT_LOG_ENABLED",
    "FACTORY_POLICY_MODULE", "FACTORY_MAX_BULK_SIZE", "FACTORY_SERIALIZE_DEPTH",
    "FACTORY_USE_COUNTER",
}

def configure_factory(**kwargs):
    """Set module-level factory settings by name (fixed: previously did setattr
    on a str constant, which silently broke). Accepts either the full setting
    name (FACTORY_MAX_BULK_SIZE=...) or the short form (max_bulk_size=...)."""
    for key, value in kwargs.items():
        name = key if key.startswith("FACTORY_") else f"FACTORY_{key.upper()}"
        if name not in _CONFIGURABLE:
            raise ConfigMissingError(f"unknown factory setting: {key}")
        globals()[name] = value

def import_policy_module(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        _logger.warning(f"Policy module {module_name} not found")
        return False

# --- grafted from original part (API stability) ---
def build(model, **fields):
    """Instantiate (not persist) a model with fields — for unit tests."""
    return model(**fields)


def _selftest() -> bool:
    import os
    import tempfile
    from sqlalchemy import create_engine, String, Integer
    from sqlalchemy.orm import mapped_column
    from scrapyard.database.base_model import IntPKModel

    class Widget(IntPKModel):
        __tablename__ = "factories_selftest_widgets"
        name: Mapped[str] = mapped_column(String(80), nullable=False)
        qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # configure_factory actually mutates module settings now
    old_domain = FACTORY_DEFAULT_DOMAIN
    configure_factory(default_domain="test.local", FACTORY_MAX_BULK_SIZE=10)
    assert FACTORY_DEFAULT_DOMAIN == "test.local"
    assert FACTORY_MAX_BULK_SIZE == 10
    try:
        configure_factory(nonsense_setting=1)
        raise AssertionError("unknown setting accepted")
    except ConfigMissingError:
        pass
    configure_factory(default_domain=old_domain, FACTORY_MAX_BULK_SIZE=100)

    # build/build_model with error mapping
    w = build_model(Widget, name="a", qty=2)
    assert w.name == "a" and w.qty == 2
    try:
        build_model(Widget, bogus_field=1)
        raise AssertionError("bad field accepted")
    except InvalidFieldError:
        pass
    assert build(Widget, name="b").name == "b"

    # serialize_model: no unsupported kwargs; depth pruning works
    data = serialize_model(w)
    assert data["name"] == "a" and data["qty"] == 2
    nested = {"a": {"b": {"c": {"d": 1}}}}
    pruned = _prune_depth(nested, 2)
    assert pruned == {"a": {"b": {"c": None}}}, pruned

    # persistence path against temp SQLite
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        engine = create_engine(f"sqlite:///{os.path.join(td, 'f.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                inst = create_model(db, Widget, name="persisted", qty=5)
                db.commit()
                assert inst.id is not None
                got = db.get(Widget, inst.id)
                assert got is not None and got.name == "persisted"
        finally:
            engine.dispose()

    # counters + unique fields
    reset_counter()
    u1 = generate_unique_field(str, "email")
    u2 = generate_unique_field(str, "email")
    assert u1 != u2 and "email" in u1

    print("factories selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
