"""
pause_condition — Define conditions under which SLA time should be paused, enabling flexible and rule-based SLA management.

### PART-META-JSON
{
  "name": "pause_condition",
  "layer": "support",
  "purpose": "Define conditions under which SLA time should be paused, enabling flexible and rule-based SLA management.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: evaluate_pause_condition(trigger_data, condition); PauseCondition(...); PauseTrigger(...).",
  "outputs": "Returns: evaluate_pause_condition -> bool.",
  "files_created": [],
  "security_notes": "Operator-configured pause expressions are evaluated with a whitelisted AST interpreter (_safe_eval_condition), NOT eval(): only numeric/bool/str constants, names resolved from the trigger data (top-level keys plus event_type/payload), and/or/not, unary +/-, arithmetic (+ - * / // % ** with an exponent size cap), chained comparisons, and `in`/`not in` against list/tuple/set literals of constants are allowed; calls, attributes, subscripts and every other syntax element raise ValueError and evaluation fails closed (no pause). Payload regex patterns are operator-supplied; invalid regexes are logged and fail closed.",
  "ai_usage": "Import what you need from `scrapyard.support.pause_condition`.",
  "example": "from scrapyard.support.pause_condition import *",
  "import_path": "scrapyard.support.pause_condition"
}
### END-PART-META
"""

from sqlalchemy import String, Text, ForeignKey, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, relationship, Session
from scrapyard.database.base_model import IntPKModel
from typing import List, Optional, Dict, Any
import ast
import operator
import re
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safe expression evaluator (replaces eval() on operator-configured strings)
# ---------------------------------------------------------------------------

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

_MAX_POW_OPERAND = 10 ** 6  # guard against DoS via huge exponentiation

_ALLOWED_CONST_TYPES = (bool, int, float, str)


def _check_safe_value(value):
    """Restrict resolved context values to safe primitives.

    Defense-in-depth: even with a whitelisted grammar, a hostile context VALUE
    (an object whose __add__/__gt__/__bool__/... runs arbitrary code) would have
    its dunder invoked the moment it reached an operator. Only primitives and
    containers thereof are allowed; anything else raises ValueError BEFORE it is
    used, so its methods are never called.
    """
    if value is None or type(value) in _ALLOWED_CONST_TYPES:
        return value
    if type(value) in (list, tuple, set, frozenset):
        for item in value:
            _check_safe_value(item)
        return value
    if type(value) is dict:
        for k, v in value.items():
            _check_safe_value(k)
            _check_safe_value(v)
        return value
    raise ValueError(f"Context value of type {type(value).__name__} not allowed in conditions")


def _safe_eval_condition(expression: str, context: Dict[str, Any]) -> bool:
    """Whitelisted AST evaluation of a pause expression (no eval()).

    Only permits: numeric/bool/str constants, names resolved from
    `context`, `and`/`or`/`not`, unary +/-, arithmetic (+ - * / // % **
    with a size guard on **), chained comparisons, and `in`/`not in`
    against list/tuple/set literals of constants. Every other syntax
    element (calls, attributes, subscripts, comprehensions, f-strings,
    ...) raises ValueError.
    """
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("Expression must be a non-empty string")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression syntax: {expression!r}") from exc

    def _collection(node: ast.AST) -> tuple:
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values = []
            for el in node.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, _ALLOWED_CONST_TYPES):
                    values.append(el.value)
                else:
                    raise ValueError("Membership collections may only contain literal constants")
            return tuple(values)
        raise ValueError("Membership target must be a list/tuple/set literal of constants")

    def _eval(node: ast.AST):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, _ALLOWED_CONST_TYPES):
                return node.value
            raise ValueError(f"Constant of type {type(node.value).__name__} not allowed in expressions")
        if isinstance(node, ast.Name):
            if node.id in context:
                return _check_safe_value(context[node.id])
            raise ValueError(f"Unknown variable in expression: {node.id!r}")
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result = True
                for value in node.values:
                    result = _eval(value)
                    if not result:
                        return result
                return result
            if isinstance(node.op, ast.Or):
                result = False
                for value in node.values:
                    result = _eval(value)
                    if result:
                        return result
                return result
            raise ValueError("Unsupported boolean operator")
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return not _eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -_eval(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +_eval(node.operand)
            raise ValueError("Unsupported unary operator")
        if isinstance(node, ast.BinOp):
            op = _BIN_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Operator {type(node.op).__name__} not allowed in expressions")
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Pow):
                if (not isinstance(left, (int, float)) or not isinstance(right, (int, float))
                        or abs(left) > _MAX_POW_OPERAND or abs(right) > 128):
                    raise ValueError("Exponentiation operands not allowed")
            return op(left, right)
        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            for cmp_op, comparator in zip(node.ops, node.comparators):
                if isinstance(cmp_op, (ast.In, ast.NotIn)):
                    right = _collection(comparator)
                    hit = left in right
                    if isinstance(cmp_op, ast.NotIn):
                        hit = not hit
                    if not hit:
                        return False
                else:
                    fn = _CMP_OPS.get(type(cmp_op))
                    if fn is None:
                        raise ValueError(f"Comparison {type(cmp_op).__name__} not allowed in expressions")
                    right = _eval(comparator)
                    if not fn(left, right):
                        return False
                left = right
            return True
        raise ValueError(f"Disallowed syntax in expression: {type(node).__name__}")

    return bool(_eval(tree))


class PauseCondition(IntPKModel):
    __tablename__ = 'pause_conditions'
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    expression: Mapped[str] = mapped_column(Text, nullable=False, default="True")
    
    triggers: Mapped[List["PauseTrigger"]] = relationship(
        "PauseTrigger", 
        back_populates="condition", 
        cascade="all, delete-orphan"
    )


class PauseTrigger(IntPKModel):
    __tablename__ = 'pause_triggers'
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_id: Mapped[int] = mapped_column(ForeignKey("pause_conditions.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_pattern: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    condition: Mapped["PauseCondition"] = relationship("PauseCondition", back_populates="triggers")


def evaluate_pause_condition(trigger_data: Dict[str, Any], condition: PauseCondition) -> bool:
    """
    Evaluate whether a pause condition should be active based on trigger data.
    
    Args:
        trigger_data: Dictionary containing event data with at least 'event_type' and optionally 'payload'
        condition: PauseCondition instance to evaluate against
        
    Returns:
        bool: True if the condition is met and pause should be activated
    """
    if not trigger_data or not isinstance(trigger_data, dict):
        return False
    
    event_type = trigger_data.get('event_type')
    if not event_type:
        return False
    
    matching_trigger = None
    for trigger in condition.triggers:
        if trigger.event_type == event_type:
            matching_trigger = trigger
            break
    
    if not matching_trigger:
        return False
    
    if matching_trigger.payload_pattern:
        payload = str(trigger_data.get('payload', ''))
        try:
            if not re.search(matching_trigger.payload_pattern, payload):
                return False
        except re.error as e:
            logger.error(f"Invalid regex pattern '{matching_trigger.payload_pattern}': {e}")
            return False
    
    expression = condition.expression or "True"
    # Expressions see top-level trigger_data keys as plain names
    # (e.g. "day in ['Saturday', 'Sunday']"), plus event_type/payload.
    context = dict(trigger_data)
    context['event_type'] = event_type
    context['payload'] = trigger_data.get('payload', {})
    try:
        return _safe_eval_condition(expression, context)
    except Exception as e:
        logger.error(f"Error evaluating expression '{expression}': {e}")
        return False


def _selftest() -> bool:
    """
    Self-contained test suite for pause_condition module.
    Uses temporary SQLite database for offline testing.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_pause_condition.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        IntPKModel.metadata.create_all(engine)
        
        try:
            with Session(engine) as session:
                condition = PauseCondition(
                    name="Weekend Maintenance Window",
                    expression="day in ['Saturday', 'Sunday']"
                )
                trigger = PauseTrigger(
                    name="Weekend Tick",
                    condition=condition,
                    event_type="calendar_tick",
                    payload_pattern=None
                )
                condition.triggers.append(trigger)
                
                session.add(condition)
                session.commit()
                
                assert condition.id is not None, "PauseCondition should have auto-generated ID"
                assert trigger.id is not None, "PauseTrigger should have auto-generated ID"
                assert trigger.condition_id == condition.id, "Foreign key should be set correctly"
                
                saturday_data = {
                    'event_type': 'calendar_tick',
                    'day': 'Saturday',
                    'payload': {'hour': 12}
                }
                result = evaluate_pause_condition(saturday_data, condition)
                assert result is True, f"Expected True for Saturday, got {result}"
                
                monday_data = {
                    'event_type': 'calendar_tick',
                    'day': 'Monday',
                    'payload': {'hour': 9}
                }
                result = evaluate_pause_condition(monday_data, condition)
                assert result is False, f"Expected False for Monday, got {result}"
                
                wrong_event_data = {
                    'event_type': 'user_login',
                    'day': 'Saturday'
                }
                result = evaluate_pause_condition(wrong_event_data, condition)
                assert result is False, "Should return False when no matching trigger event_type"
                
                stmt = select(PauseCondition).where(PauseCondition.name == "Weekend Maintenance Window")
                fetched_condition = session.execute(stmt).scalar_one()
                assert fetched_condition is not None, "Should fetch condition from database"
                assert len(fetched_condition.triggers) == 1, "Should load related triggers"
                assert fetched_condition.triggers[0].event_type == "calendar_tick"
                
                error_condition = PauseCondition(
                    name="Critical Error Pause",
                    expression="True"
                )
                error_trigger = PauseTrigger(
                    name="Critical DB Error",
                    condition=error_condition,
                    event_type="error_logged",
                    payload_pattern="critical.*database"
                )
                error_condition.triggers.append(error_trigger)
                session.add(error_condition)
                session.commit()
                
                critical_error_data = {
                    'event_type': 'error_logged',
                    'payload': 'critical database connection failure'
                }
                result = evaluate_pause_condition(critical_error_data, error_condition)
                assert result is True, "Should match payload pattern"
                
                minor_error_data = {
                    'event_type': 'error_logged',
                    'payload': 'minor warning'
                }
                result = evaluate_pause_condition(minor_error_data, error_condition)
                assert result is False, "Should not match payload pattern"
                
                simple_condition = PauseCondition(
                    name="Always Pause on Shutdown",
                    expression=""
                )
                shutdown_trigger = PauseTrigger(
                    name="System Shutdown",
                    condition=simple_condition,
                    event_type="shutdown_initiated",
                    payload_pattern=None
                )
                simple_condition.triggers.append(shutdown_trigger)
                session.add(simple_condition)
                session.commit()
                
                shutdown_data = {'event_type': 'shutdown_initiated'}
                result = evaluate_pause_condition(shutdown_data, simple_condition)
                assert result is True, "Empty expression should default to True"

                # Injection tests: hostile expressions must raise ValueError
                # in the safe evaluator and fail closed (no pause) end-to-end
                for hostile in (
                    "().__class__.__mro__",
                    "__import__('os').system('echo pwned')",
                    "event_type.__class__",
                    "open('x')",
                    "[x for x in (1,)]",
                    "day in [open('x')]",
                    "data.get('day')",  # attribute/method access is not allowed
                ):
                    try:
                        _safe_eval_condition(hostile, {'event_type': 'x', 'day': 'Saturday'})
                        raise AssertionError(f"hostile expression not rejected: {hostile!r}")
                    except ValueError:
                        pass

                evil_condition = PauseCondition(
                    name="Injection Attempt",
                    expression="().__class__.__mro__"
                )
                evil_trigger = PauseTrigger(
                    name="Evil Trigger",
                    condition=evil_condition,
                    event_type="evil_event",
                    payload_pattern=None
                )
                evil_condition.triggers.append(evil_trigger)
                session.add(evil_condition)
                session.commit()

                result = evaluate_pause_condition({'event_type': 'evil_event'}, evil_condition)
                assert result is False, "Hostile expression must fail closed, not execute"

                # EXPLOIT REGRESSION: a hostile context VALUE must not have its
                # dunders invoked. `x + 1` would call Hostile.__add__ if the
                # value reached the operator; _check_safe_value rejects it first.
                class _Hostile:
                    invoked = False
                    def __add__(self, other): _Hostile.invoked = True; return 0
                    def __radd__(self, other): _Hostile.invoked = True; return 0
                    def __gt__(self, other): _Hostile.invoked = True; return True
                    def __bool__(self): _Hostile.invoked = True; return True
                try:
                    _safe_eval_condition("x + 1 > 5", {"x": _Hostile()})
                    raise AssertionError("hostile context object was evaluated")
                except ValueError:
                    pass
                assert _Hostile.invoked is False, "hostile context object had a dunder invoked"

            logger.info("All selftests passed successfully")
            return True
            
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
