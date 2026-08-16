"""
validation — Reusable request/response model patterns and validators.

### PART-META-JSON
{
  "name": "validation",
  "layer": "api",
  "purpose": "Dict- and model-level validation helpers on pydantic v2: required-field checks, rule maps (callable per field, bool or (bool, msg) results), nested-dict validation, model re-validation against rule maps, list filtering, in-memory pagination, API serialization/deserialization, and audit/metric hook registries fired on every validation outcome.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "pydantic",
    "fastapi"
  ],
  "inputs": "Request payload dicts or pydantic models plus rule maps {field: callable}.",
  "outputs": "The validated data (unchanged) or a ValidationError carrying a {field: message} map.",
  "files_created": [],
  "security_notes": "ValidationError messages echo rule-provided text and field NAMES, not raw input values — keep custom rule messages free of reflected input to avoid leaking or log-injecting payload content. Rules are trusted callables supplied by application code, never built from user input. serialize_for_api honours exclude lists so response models can drop sensitive fields (password hashes, tokens) at the boundary.",
  "ai_usage": "validate(payload, {'email': lambda v: ('@' in (v or ''), 'invalid email')}); require_fields(payload, 'name').",
  "example": "validate({'qty': 5}, {'qty': lambda v: (v > 0, 'must be positive')})",
  "import_path": "scrapyard.api.validation"
}
### END-PART-META
"""
from __future__ import annotations

import typing as t

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

STATUS = "core"


class ValidationError(ValueError):
    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


# --- hook registries (real: fired on every validation outcome) ---
_audit_hooks: list[t.Callable[[dict, t.Optional[dict]], None]] = []
_metric_hooks: list[t.Callable[[str, bool], None]] = []


def add_audit_hook(func: t.Callable[[dict, t.Optional[dict]], None]) -> None:
    """Register callable(data, errors_or_None) fired after each validate call."""
    if not callable(func):
        raise TypeError("audit hook must be callable")
    _audit_hooks.append(func)


def add_metric_hook(func: t.Callable[[str, bool], None]) -> None:
    """Register callable(operation, success) fired after each validate call."""
    if not callable(func):
        raise TypeError("metric hook must be callable")
    _metric_hooks.append(func)


def clear_hooks() -> None:
    _audit_hooks.clear()
    _metric_hooks.clear()


def _notify(operation: str, data: dict, errors: t.Optional[dict]) -> None:
    for hook in _audit_hooks:
        try:
            hook(data, errors)
        except Exception:
            pass  # observers must never break validation
    for hook in _metric_hooks:
        try:
            hook(operation, errors is None)
        except Exception:
            pass


def _apply_rule(rule: t.Callable, value: t.Any) -> tuple[bool, str]:
    res = rule(value)
    if isinstance(res, tuple):
        ok, msg = res
    else:
        ok, msg = res, "invalid"
    return bool(ok), msg


def require_fields(data: dict, *fields: str) -> None:
    missing = {f: "required" for f in fields if data.get(f) in (None, "")}
    if missing:
        _notify("require_fields", data, missing)
        raise ValidationError(missing)
    _notify("require_fields", data, None)


def validate(data: dict, rules: dict) -> dict:
    """rules: {field: callable(value)->bool or (bool, msg)}. Raises ValidationError."""
    errors = {}
    for field, rule in rules.items():
        ok, msg = _apply_rule(rule, data.get(field))
        if not ok:
            errors[field] = msg
    if errors:
        _notify("validate", data, errors)
        raise ValidationError(errors)
    _notify("validate", data, None)
    return data


def validate_model(model: BaseModel, rules: dict[str, t.Any]) -> BaseModel:
    """Check a pydantic v2 model instance against a rule map; every rule field
    must exist on the model. Returns a re-validated copy of the model."""
    values = model.model_dump()
    errors: dict = {}
    for field, rule in rules.items():
        if field not in type(model).model_fields:
            errors[field] = "unknown field"
            continue
        ok, msg = _apply_rule(rule, values.get(field))
        if not ok:
            errors[field] = msg
    if errors:
        _notify("validate_model", values, errors)
        raise ValidationError(errors)
    _notify("validate_model", values, None)
    return type(model).model_validate(values)


def validate_nested(data: dict, rules: dict, depth: int = 2) -> dict:
    """Apply a (possibly nested) rule map to a nested dict, up to ``depth`` levels."""
    def _walk(d: dict, r: dict, dpt: int) -> None:
        for k, v in d.items():
            sub_rule = r.get(k)
            if isinstance(v, dict) and dpt < depth and isinstance(sub_rule, dict):
                _walk(v, sub_rule, dpt + 1)
            elif sub_rule is not None and callable(sub_rule):
                ok, msg = _apply_rule(sub_rule, v)
                if not ok:
                    raise ValidationError({k: msg})
    _walk(data, rules, 0)
    return data


def apply_filters(data: list[dict], filters: dict) -> list[dict]:
    """Filter dicts. Each filter value may be: a callable(value)->bool, a tuple
    (op, operand) applied as op(value, operand), or a literal for equality."""
    def keep(d: dict) -> bool:
        for k, v in filters.items():
            value = d.get(k)
            if callable(v):
                if not v(value):
                    return False
            elif isinstance(v, tuple) and len(v) == 2 and callable(v[0]):
                op, operand = v
                if not op(value, operand):
                    return False
            elif value != v:
                return False
        return True

    return [d for d in data if keep(d)]


def paginate(items: list[dict], page: int = 1, page_size: int = 20) -> dict:
    page = max(1, page)
    page_size = max(1, page_size)
    start = (page - 1) * page_size
    return {
        "items": items[start:start + page_size],
        "total_pages": (len(items) + page_size - 1) // page_size,
        "current_page": page,
        "page_size": page_size,
    }


def serialize_for_api(obj: t.Any, exclude: list[str] | None = None) -> t.Any:
    if isinstance(obj, BaseModel):
        return jsonable_encoder(obj.model_dump(exclude=set(exclude) if exclude else None))
    if isinstance(obj, (list, tuple)):
        return [serialize_for_api(item, exclude) for item in obj]
    raise TypeError("Unsupported type for serialization")


def deserialize_from_api(data: dict, model: t.Type[BaseModel]) -> BaseModel:
    try:
        return model.model_validate(data)
    except PydanticValidationError as e:
        raise ValidationError({str(err["loc"][0]) if err["loc"] else "__root__": err["msg"]
                               for err in e.errors()}) from e


def validate_and_serialize(data: dict, model: t.Type[BaseModel],
                           rules: dict | None = None,
                           exclude: list[str] | None = None) -> dict:
    validated = validate_model(deserialize_from_api(data, model), rules or {})
    return serialize_for_api(validated, exclude)


def validate_and_paginate(data: list[dict], model: t.Type[BaseModel], rules: dict,
                          page: int = 1, page_size: int = 20) -> dict:
    result = paginate(data, page, page_size)
    result["items"] = [validate_model(deserialize_from_api(item, model), rules)
                       for item in result["items"]]
    return result


def _selftest() -> None:
    import operator

    clear_hooks()

    # require_fields + validate
    require_fields({"a": 1, "b": "x"}, "a", "b")
    try:
        require_fields({"a": 1, "b": ""}, "a", "b", "c")
        raise AssertionError("missing fields accepted")
    except ValidationError as e:
        assert e.errors == {"b": "required", "c": "required"}
    validate({"qty": 5}, {"qty": lambda v: (v > 0, "must be positive")})
    try:
        validate({"qty": -1}, {"qty": lambda v: (v > 0, "must be positive")})
        raise AssertionError("bad value accepted")
    except ValidationError as e:
        assert e.errors == {"qty": "must be positive"}

    # model validation on pydantic v2
    class Item(BaseModel):
        name: str
        qty: int = 0

    item = Item(name="ok", qty=3)
    out = validate_model(item, {"qty": lambda v: v >= 0})
    assert isinstance(out, Item) and out.qty == 3
    try:
        validate_model(item, {"qty": lambda v: (v > 5, "too small")})
        raise AssertionError("failing rule accepted")
    except ValidationError as e:
        assert e.errors == {"qty": "too small"}
    try:
        validate_model(item, {"ghost": lambda v: True})
        raise AssertionError("unknown rule field accepted")
    except ValidationError as e:
        assert e.errors == {"ghost": "unknown field"}

    # nested validation
    data = {"user": {"email": "a@b.c", "age": 30}}
    validate_nested(data, {"user": {"age": lambda v: (v >= 18, "adults only")}})
    try:
        validate_nested({"user": {"age": 10}}, {"user": {"age": lambda v: (v >= 18, "adults only")}})
        raise AssertionError("nested rule ignored")
    except ValidationError as e:
        assert e.errors == {"age": "adults only"}

    # filters: callable, (op, operand), literal
    rows = [{"n": 1, "tag": "a"}, {"n": 5, "tag": "b"}, {"n": 9, "tag": "a"}]
    assert apply_filters(rows, {"tag": "a"}) == [rows[0], rows[2]]
    assert apply_filters(rows, {"n": (operator.gt, 4)}) == [rows[1], rows[2]]
    assert apply_filters(rows, {"n": lambda v: v % 2 == 1, "tag": "a"}) == [rows[0], rows[2]]

    # pagination
    items = [{"i": i} for i in range(45)]
    p = paginate(items, page=3, page_size=20)
    assert len(p["items"]) == 5 and p["total_pages"] == 3 and p["current_page"] == 3
    assert paginate(items, page=-4, page_size=0)["current_page"] == 1

    # serialization round trips + exclude
    class User(BaseModel):
        name: str
        password_hash: str = "x"

    u = User(name="ann")
    blob = serialize_for_api(u, exclude=["password_hash"])
    assert blob == {"name": "ann"}
    assert serialize_for_api([u]) == [{"name": "ann", "password_hash": "x"}]
    try:
        serialize_for_api(object())
        raise AssertionError("bad type serialized")
    except TypeError:
        pass
    back = deserialize_from_api({"name": "bob"}, User)
    assert isinstance(back, User) and back.name == "bob"
    try:
        deserialize_from_api({"name": 12345678}, User)
        raise AssertionError("bad payload deserialized")
    except ValidationError as e:
        assert "name" in e.errors

    # combined helpers
    out = validate_and_serialize({"name": "cat"}, User,
                                 rules={"name": lambda v: len(v) >= 3},
                                 exclude=["password_hash"])
    assert out == {"name": "cat"}
    page = validate_and_paginate([{"name": "a1"}, {"name": "b2"}], User, {}, page=1, page_size=1)
    assert isinstance(page["items"][0], User) and page["total_pages"] == 2

    # hooks fire with outcomes
    audits: list = []
    metrics: list = []
    add_audit_hook(lambda data, errors: audits.append(errors))
    add_metric_hook(lambda op, ok: metrics.append((op, ok)))
    validate({"x": 1}, {"x": lambda v: True})
    try:
        validate({"x": 1}, {"x": lambda v: (False, "no")})
    except ValidationError:
        pass
    assert audits == [None, {"x": "no"}]
    assert metrics == [("validate", True), ("validate", False)]
    clear_hooks()

    print("validation selftest: PASS")


if __name__ == "__main__":
    _selftest()
