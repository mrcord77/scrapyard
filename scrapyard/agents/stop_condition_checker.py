"""
stop_condition_checker — ** The `stop_condition_checker` module evaluates predefined stop conditions to determine whether an agent should terminate its execution, ensuring safe and controlled operation. It relies on the plann

### PART-META-JSON
{
  "name": "stop_condition_checker",
  "layer": "agents",
  "purpose": "Evaluates predefined stop conditions to determine whether an agent should terminate its execution, ensuring safe and controlled operation. It relies on the plann.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: check_stop_conditions(state); eval_stop_condition(condition, **kwargs); StopCondition(...); AgentState(...).",
  "outputs": "Returns: check_stop_conditions -> bool; eval_stop_condition -> bool.",
  "files_created": [],
  "security_notes": "Agent-configured stop conditions are evaluated with a whitelisted AST interpreter (_safe_eval_condition), NOT eval(): only numeric/bool constants, state variable names, and/or/not, unary +/-, arithmetic (+ - * / // % ** with an exponent size cap) and chained comparisons are allowed; calls, attributes, subscripts, strings and every other syntax element raise ValueError. Unknown variables and disallowed syntax fail closed (condition treated as not met).",
  "ai_usage": "Import what you need from `scrapyard.agents.stop_condition_checker`.",
  "example": "from scrapyard.agents.stop_condition_checker import *",
  "import_path": "scrapyard.agents.stop_condition_checker"
}
### END-PART-META
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any
import ast
import operator
import os
import logging
import sqlite3
import tempfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safe condition evaluator (replaces eval() on agent-configured strings)
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

_SAFE_VALUE_TYPES = (bool, int, float, str)


def _check_safe_value(value):
    """Restrict resolved context values to safe primitives.

    Defense-in-depth: even with a whitelisted grammar, a hostile context VALUE
    (an object whose __add__/__gt__/__bool__/... runs arbitrary code) would have
    its dunder invoked the moment it reached an operator. Only primitives and
    containers thereof are allowed; anything else raises ValueError BEFORE it is
    used, so its methods are never called.
    """
    if value is None or type(value) in _SAFE_VALUE_TYPES:
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
    """Whitelisted AST evaluation of a stop-condition expression (no eval()).

    Only permits: numeric/bool constants, names resolved from `context`,
    `and`/`or`/`not`, unary +/-, arithmetic (+ - * / // % ** with a size
    guard on **) and chained comparisons. Every other syntax element
    (calls, attributes, subscripts, strings, comprehensions, f-strings,
    ...) raises ValueError.
    """
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("Condition must be a non-empty string")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid condition syntax: {expression!r}") from exc

    def _eval(node: ast.AST):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (bool, int, float)):
                return node.value
            raise ValueError(f"Constant of type {type(node.value).__name__} not allowed in conditions")
        if isinstance(node, ast.Name):
            if node.id in context:
                return _check_safe_value(context[node.id])
            raise ValueError(f"Unknown variable in condition: {node.id!r}")
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
                raise ValueError(f"Operator {type(node.op).__name__} not allowed in conditions")
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
                fn = _CMP_OPS.get(type(cmp_op))
                if fn is None:
                    raise ValueError(f"Comparison {type(cmp_op).__name__} not allowed in conditions")
                right = _eval(comparator)
                if not fn(left, right):
                    return False
                left = right
            return True
        raise ValueError(f"Disallowed syntax in condition: {type(node).__name__}")

    return bool(_eval(tree))

@dataclass
class StopCondition:
    condition: str
    value: Any

@dataclass
class AgentState:
    stop_conditions: List[StopCondition] = field(default_factory=list)

def check_stop_conditions(state: Dict[str, Any]) -> bool:
    """
    Evaluates predefined stop conditions based on the agent state.

    :param state: A dictionary containing the current state of the agent.
    :return: True if any stop condition is met, False otherwise.
    """
    if not isinstance(state, dict):
        logger.warning("Invalid state provided. Expected a dictionary.")
        return False

    # Convert incoming state to AgentState dataclass for type safety
    try:
        agent_state = AgentState(stop_conditions=[StopCondition(k, v) for k, v in state.get('stop_conditions', {}).items()])
    except Exception as e:
        logger.error(f"Failed to parse stop conditions: {e}")
        return False

    # Check each stop condition
    for cond in agent_state.stop_conditions:
        if eval_stop_condition(cond.condition, **state):
            logger.info(f"Stop condition met: {cond.condition}")
            return True

    logger.debug("No stop conditions met.")
    return False

def eval_stop_condition(condition: str, **kwargs) -> bool:
    """
    Evaluates a single stop condition string using the provided state.

    :param condition: A string representing the stop condition to evaluate.
    :param kwargs: Additional keyword arguments providing context for evaluation.
    :return: True if the condition is met, False otherwise.
    """
    try:
        # Whitelisted AST evaluation; disallowed syntax raises ValueError
        return _safe_eval_condition(condition, {**kwargs})
    except Exception as e:
        logger.error(f"Error evaluating stop condition '{condition}': {e}")
        return False

def _selftest() -> bool:
    """
    Offline self-test for the stop condition checker.

    :return: True if all tests pass, False otherwise.
    """
    # Test data: stop-condition keys are expressions over top-level state names
    test_state = {
        'stop_conditions': {
            'fuel_level < 0.2': 'low fuel',
            'temperature > 90': 'overheating',
            'engine_failure': 'engine failed',
        },
        'fuel_level': 0.1,
        'temperature': 95,
        'engine_failure': True,
    }

    # Expected outcomes
    expected_outcomes = [
        (test_state, True),  # All conditions are met
        ({}, False),         # No stop conditions defined
        ({'stop_conditions': {}}, False),  # Empty dictionary for stop conditions
        ({'stop_conditions': {'fuel_level < 0.2': 'x'}, 'fuel_level': 0.9}, False),  # Condition not met
        ({'stop_conditions': {'unknown_var > 1': 'x'}}, False),  # Unknown variable fails closed
        # Injection attempts must fail closed, never execute
        ({'stop_conditions': {"__import__('os').system('echo pwned')": 'x'}}, False),
        ({'stop_conditions': {"().__class__.__mro__": 'x'}}, False),
    ]

    success = True

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = os.path.join(tmp_dir, 'test.db')
        conn = sqlite3.connect(db_path)

        for state, expected in expected_outcomes:
            result = check_stop_conditions(state)
            if result != expected:
                logger.error(f"Test failed: {state} -> Expected: {expected}, Got: {result}")
                success = False

    # Injection tests: the safe evaluator must raise ValueError, not execute
    for hostile in [
        "__import__('os').system('echo pwned')",
        "().__class__.__mro__",
        "fuel_level.__class__",
        "open('x')",
        "[x for x in (1,)]",
        "'a' == 'a'",  # strings are outside this part's condition vocabulary
        "",
    ]:
        try:
            _safe_eval_condition(hostile, {'fuel_level': 0.1})
            logger.error(f"Hostile expression not rejected: {hostile!r}")
            success = False
        except ValueError:
            pass

    # EXPLOIT REGRESSION: a hostile context VALUE must not have its dunders
    # invoked. `x + 1` would call Hostile.__add__ if the value reached the
    # operator; _check_safe_value rejects the non-primitive first.
    class _Hostile:
        invoked = False
        def __add__(self, other): _Hostile.invoked = True; return 0
        def __radd__(self, other): _Hostile.invoked = True; return 0
        def __gt__(self, other): _Hostile.invoked = True; return True
        def __bool__(self): _Hostile.invoked = True; return True
    try:
        _safe_eval_condition("x + 1 > 5", {"x": _Hostile()})
        logger.error("hostile context object was evaluated")
        success = False
    except ValueError:
        pass
    if _Hostile.invoked:
        logger.error("hostile context object had a dunder invoked")
        success = False

    return success

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    if _selftest():
        print("Self-test passed successfully.")
    else:
        print("Self-test failed.")
        raise SystemExit(1)
