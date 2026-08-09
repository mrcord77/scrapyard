"""
contract_tests — Validate responses against the app's declared OpenAPI contract.

### PART-META-JSON
{
  "name": "contract_tests",
  "layer": "testing",
  "purpose": "OpenAPI contract enforcement for FastAPI apps: resolve the response model for a route via route introspection (route.response_model, openapi() schema fallback) and validate live responses against it; plus generic pydantic/shape/status assertions.",
  "addition": true,
  "status": "core",
  "dependencies": ["fastapi"],
  "inputs": "A FastAPI app object, route paths/methods, response objects (TestClient/httpx responses or fastapi Response), pydantic models.",
  "outputs": "ValidationResult objects (ok + message); resolved pydantic model classes; shape/status check dicts.",
  "files_created": [],
  "security_notes": "Validation failure messages can echo response payload fragments - route them to test logs only, never to end users. strict mode raises on violations so CI fails closed. No network I/O: responses are validated in-process.",
  "ai_usage": "model = get_model_for_route(app, '/items/1'); enforce_openapi_contract('/items/1', client.get('/items/1'), app=app). set_strict_mode(True) to raise on contract violations.",
  "example": "from scrapyard.testing.contract_tests import enforce_openapi_contract, get_model_for_route",
  "import_path": "scrapyard.testing.contract_tests"
}
### END-PART-META
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, List, Optional, Type

from fastapi import Response
from pydantic import BaseModel, ValidationError as ModelValidationError

STATUS = "core"
log = logging.getLogger("scrapyard.testing.contract_tests")

strict_mode = False


class OpenAPIMissingError(Exception):
    pass


class UnexpectedResponseFormat(Exception):
    pass


class ContractViolation(Exception):
    pass


class ValidationResult:
    def __init__(self, ok: bool, message: Optional[str] = None):
        self.ok = ok
        self.message = message

    def __repr__(self):
        return f"ValidationResult(ok={self.ok}, message={self.message!r})"


def _extract_json(response: Any) -> Any:
    """Get the JSON payload from an httpx/TestClient response (has .json()) or a
    fastapi/starlette Response (has .body). Fixed: fastapi.Response has no .json()."""
    json_attr = getattr(response, "json", None)
    if callable(json_attr):
        return json_attr()
    body = getattr(response, "body", None)
    if body is not None:
        return json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)
    raise UnexpectedResponseFormat(
        f"cannot extract JSON from {type(response).__name__}")


def validate_response_with_model(response: Any, model: Type[BaseModel]) -> ValidationResult:
    try:
        data = _extract_json(response)
        model(**data)
        return ValidationResult(ok=True)
    except (ValueError, ModelValidationError, UnexpectedResponseFormat) as e:
        return ValidationResult(ok=False, message=str(e))


def get_model_for_route(app: Any, route_path: str, method: str = "GET") -> Type[BaseModel]:
    """Resolve the pydantic response model declared for a route (the previously
    NotImplementedError headline).

    Primary: FastAPI route introspection - route.response_model on the matching
    APIRoute. Fallback: confirm the route exists in app.openapi() and report that
    no typed model was declared. Raises OpenAPIMissingError when the route is
    unknown or declares no response model.
    """
    from fastapi.routing import APIRoute

    method = method.upper()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == route_path and method in route.methods:
            model = route.response_model
            if model is not None and isinstance(model, type) and issubclass(model, BaseModel):
                return model
            raise OpenAPIMissingError(
                f"route {method} {route_path} declares no pydantic response_model")

    # fallback: openapi() schema lookup for a clearer error
    try:
        spec = app.openapi()
        if route_path in spec.get("paths", {}):
            raise OpenAPIMissingError(
                f"route {route_path} exists in the OpenAPI schema but has no "
                f"introspectable response model for {method}")
    except OpenAPIMissingError:
        raise
    except Exception:
        pass
    raise OpenAPIMissingError(f"No OpenAPI definition found for route {route_path}")


def enforce_openapi_contract(route: str, response: Any, app: Any = None,
                             method: str = "GET") -> ValidationResult:
    """Validate a response against the model the app declares for `route`.

    Returns the REAL inner validation result (previously discarded). In strict
    mode a violation raises ContractViolation instead of returning ok=False.
    """
    if app is None:
        raise OpenAPIMissingError(
            "enforce_openapi_contract requires the app object to resolve the contract")
    try:
        model = get_model_for_route(app, route, method)
        result = validate_response_with_model(response, model)
    except OpenAPIMissingError as e:
        result = ValidationResult(ok=False, message=str(e))
    if not result.ok:
        log_validation_failure({}, result.message or "unknown", route)
        if strict_mode:
            raise ContractViolation(f"{route}: {result.message}")
    return result


def validate_multiple_responses(responses: List[Any],
                                models: List[Type[BaseModel]]) -> List[ValidationResult]:
    return [validate_response_with_model(r, m) for r, m in zip(responses, models)]


def apply_custom_rules(data: dict, rules: List[Callable[[dict], bool]]) -> ValidationResult:
    if not all(rule(data) for rule in rules):
        return ValidationResult(ok=False, message="Custom validation rules failed")
    return ValidationResult(ok=True)


def check_serialization(data: dict, expected_type: Type[BaseModel]) -> ValidationResult:
    try:
        expected_type(**data)
        return ValidationResult(ok=True)
    except (ValueError, ModelValidationError) as e:
        return ValidationResult(ok=False, message=str(e))


def log_validation_failure(data: dict, error: str, route: str):
    log.warning("contract validation failed route=%s error=%s", route, error)


def set_strict_mode(strict: bool = False):
    global strict_mode
    strict_mode = strict


async def validate_async_response(response: Awaitable[Any],
                                  model: Type[BaseModel]) -> ValidationResult:
    async_response = await response
    return validate_response_with_model(async_response, model)


# --- grafted from original part (API stability) ---
def assert_response_shape(data: dict, required_keys: list[str]) -> dict:
    """Check an API response contains the required keys (schema contract)."""
    missing = [k for k in required_keys if k not in data]
    return {"ok": not missing, "missing": missing}


def assert_status(response, expected: int) -> dict:
    actual = getattr(response, "status_code", getattr(response, "status", None))
    return {"ok": actual == expected, "actual": actual, "expected": expected}


def _selftest() -> bool:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    class Item(BaseModel):
        id: int
        name: str

    app = FastAPI()

    @app.get("/items/1", response_model=Item)
    def get_item():
        return {"id": 1, "name": "widget"}

    @app.get("/untyped")
    def untyped():
        return {"anything": True}

    @app.get("/broken", response_model=Item)
    def broken():
        # deliberately violates its own declared contract
        return Response(content='{"id": "not-an-int"}', media_type="application/json")

    # headline: model resolution via route introspection WORKS now
    assert get_model_for_route(app, "/items/1") is Item
    for bad_route, err_frag in (("/untyped", "no pydantic response_model"),
                                ("/missing", "No OpenAPI definition")):
        try:
            get_model_for_route(app, bad_route)
            raise AssertionError(f"resolved model for {bad_route}")
        except OpenAPIMissingError as e:
            assert err_frag in str(e), str(e)

    with TestClient(app) as client:
        good = client.get("/items/1")
        bad = client.get("/broken")

        # enforcement returns the real validation result
        assert enforce_openapi_contract("/items/1", good, app=app).ok
        r = enforce_openapi_contract("/broken", bad, app=app)
        assert not r.ok and r.message

        # strict mode raises
        set_strict_mode(True)
        try:
            enforce_openapi_contract("/broken", bad, app=app)
            raise AssertionError("strict mode did not raise")
        except ContractViolation:
            pass
        finally:
            set_strict_mode(False)

        # multiple + direct model validation, on TestClient responses
        results = validate_multiple_responses([good, bad], [Item, Item])
        assert results[0].ok and not results[1].ok

    # fastapi Response objects (no .json()) are handled too - the old crash
    fa_resp = Response(content='{"id": 2, "name": "x"}', media_type="application/json")
    assert validate_response_with_model(fa_resp, Item).ok
    assert not validate_response_with_model(
        Response(content='{"id": "z"}'), Item).ok

    # aux checks
    assert apply_custom_rules({"a": 1}, [lambda d: d["a"] == 1]).ok
    assert not apply_custom_rules({"a": 1}, [lambda d: d["a"] == 2]).ok
    assert check_serialization({"id": 3, "name": "n"}, Item).ok
    assert not check_serialization({"id": "x"}, Item).ok
    assert assert_response_shape({"a": 1, "b": 2}, ["a", "b"])["ok"]
    assert assert_response_shape({"a": 1}, ["a", "b"])["missing"] == ["b"]
    assert assert_status(fa_resp, 200)["ok"]

    # async wrapper
    import asyncio

    async def _fut():
        return fa_resp

    assert asyncio.run(validate_async_response(_fut(), Item)).ok

    print("contract_tests selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
