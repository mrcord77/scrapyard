"""
policy_validation - Validate expenses against policy rules and category limits.

### PART-META-JSON
{
  "name": "policy_validation",
  "layer": "expenses",
  "purpose": "Validate expenses against policy rules and category limits.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "validate_policy(expense) -> Optional[PolicyViolation]; check_limit(category, amount).",
  "outputs": "PolicyRule / PolicyLimit rows; PolicyViolation results describing breaches.",
  "files_created": [],
  "security_notes": "Money-guarding control: category limits are numeric rows compared in code. Rule condition strings are DB-sourced and evaluated with a whitelisted AST interpreter (_safe_eval_condition), NOT eval(): only numeric/bool constants, context names (amount, category_id), and/or/not, unary +/-, arithmetic (+ - * / // % ** with an exponent size cap) and chained comparisons are allowed; calls, attributes, subscripts, strings and every other syntax element raise ValueError, and the rule is then treated as not applying (a malformed block rule does NOT block - review rule expressions at write time). Float amounts: keep limits/amounts to 2dp; the reimbursement ledger is the authoritative record.",
  "ai_usage": "Import what you need from `scrapyard.expenses.policy_validation`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.expenses.policy_validation import validate_policy",
  "import_path": "scrapyard.expenses.policy_validation"
}
### END-PART-META
"""
import ast
import logging
import operator
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from sqlalchemy import Boolean, create_engine, Engine, Float, Integer, select, String, Text
from sqlalchemy.orm import Mapped, mapped_column, Session

from scrapyard.database.base_model import IntPKModel

try:
    from scrapyard.expenses.models import Category, Expense
except Exception:  # pragma: no cover
    class Category(Protocol):
        """Protocol stand-in for scrapyard.expenses.models.Category."""
        id: int

    class Expense(Protocol):
        """Protocol stand-in for scrapyard.expenses.models.Expense."""
        amount: float
        category: Category


logger: logging.Logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None

# ---------------------------------------------------------------------------
# Safe condition evaluator (replaces eval() on DB-sourced rule strings)
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


def _safe_eval_condition(expression: str, context: dict[str, Any]) -> bool:
    """Whitelisted AST evaluation of a policy-rule condition (no eval()).

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


class PolicyRule(IntPKModel):
    """Database-backed policy rule definition."""

    __tablename__ = "policy_rule"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    condition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(50), default="block", nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PolicyLimit(IntPKModel):
    """Category-specific financial threshold."""

    __tablename__ = "policy_limit"

    category_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    max_amount: Mapped[float] = mapped_column(Float, nullable=False)


class PolicyViolation(Exception):
    """Structured exception raised when an expense violates a policy."""

    def __init__(
        self,
        message: str,
        rule: Optional[str] = None,
        category_id: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.rule = rule
        self.category_id = category_id

    def __str__(self) -> str:
        return self.message


def _set_engine(engine: Engine) -> None:
    """Configure the engine used for database-backed policy lookups."""
    global _engine
    _engine = engine


def _get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Policy validation engine has not been configured")
    return _engine


def _expense_context(expense: Expense) -> dict[str, Any]:
    """Extract validation context from an expense-like object."""
    amount = float(getattr(expense, "amount", 0.0))
    category = getattr(expense, "category", None)
    category_id: Optional[int] = None
    if category is not None:
        category_id = getattr(category, "id", None)
    if category_id is None:
        category_id = getattr(expense, "category_id", None)
    return {"amount": amount, "category_id": category_id}


def validate_policy(expense: Expense) -> Optional[PolicyViolation]:
    """
    Validate an expense against active policy rules and category limits.

    Returns ``None`` when the expense passes all checks. Raises
    :class:`PolicyViolation` when a rule or limit blocks the expense.
    """
    engine = _get_engine()
    context = _expense_context(expense)
    amount = context["amount"]
    category_id = context["category_id"]

    logger.info(
        "Validating expense",
        extra={"amount": amount, "category_id": category_id},
    )

    with Session(engine) as session:
        limit = session.scalar(
            select(PolicyLimit).where(PolicyLimit.category_id == category_id)
        )
        if limit is not None and amount > limit.max_amount:
            message = (
                f"Amount {amount} exceeds category limit {limit.max_amount}"
            )
            logger.warning(message, extra={"category_id": category_id})
            raise PolicyViolation(message, category_id=category_id)

        rules = session.scalars(
            select(PolicyRule).where(PolicyRule.active == True)  # noqa: E712
        ).all()
        for rule in rules:
            if rule.category_id is not None and rule.category_id != category_id:
                continue

            applies = True
            if rule.condition:
                try:
                    applies = _safe_eval_condition(rule.condition, context)
                except Exception:
                    applies = False

            if applies and rule.action == "block":
                message = rule.message or f"Blocked by policy rule '{rule.name}'"
                logger.warning(
                    message,
                    extra={"rule": rule.name, "category_id": category_id},
                )
                raise PolicyViolation(
                    message, rule=rule.name, category_id=category_id
                )

    logger.info("Expense passed policy validation", extra=context)
    return None


def check_limit(category: Category, amount: float) -> bool:
    """
    Return ``True`` if *amount* is within the configured limit for *category*.
    """
    engine = _get_engine()
    category_id = getattr(category, "id", None)
    if category_id is None:
        return False

    with Session(engine) as session:
        limit = session.scalar(
            select(PolicyLimit).where(PolicyLimit.category_id == category_id)
        )
        if limit is None:
            return True
        return amount <= limit.max_amount


def _selftest() -> None:
    """Offline self-test using a temporary SQLite database."""
    start = time.monotonic()
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    engine: Optional[Engine] = None

    try:
        db_path = os.path.join(tmpdir.name, "policy_test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        _set_engine(engine)

        IntPKModel.metadata.create_all(engine)

        with Session(engine) as session:
            session.add(
                PolicyLimit(category_id=1, max_amount=100.0)
            )
            session.add(
                PolicyRule(
                    name="block_large_meals",
                    condition="amount > 50",
                    action="block",
                    message="Meal expenses over $50 are blocked",
                    category_id=1,
                )
            )
            session.commit()

        @dataclass
        class FakeCategory:
            id: int
            name: str

        @dataclass
        class FakeExpense:
            amount: float
            category: FakeCategory

        meals = FakeCategory(id=1, name="Meals")
        valid_expense = FakeExpense(amount=30.0, category=meals)
        blocked_expense = FakeExpense(amount=75.0, category=meals)
        over_limit_expense = FakeExpense(amount=150.0, category=meals)

        assert validate_policy(valid_expense) is None

        try:
            validate_policy(blocked_expense)
            raise AssertionError("Expected PolicyViolation for blocked expense")
        except PolicyViolation as exc:
            assert "over $50" in exc.message

        assert check_limit(meals, 80.0) is True
        assert check_limit(meals, 120.0) is False

        try:
            validate_policy(over_limit_expense)
            raise AssertionError("Expected PolicyViolation for over-limit expense")
        except PolicyViolation as exc:
            assert "exceeds category limit" in exc.message

        # Injection tests: the safe evaluator must raise ValueError, not execute
        for hostile in (
            "().__class__.__mro__",
            "__import__('os').system('echo pwned')",
            "amount.__class__",
            "open('x')",
            "[x for x in (1,)]",
            "'a' == 'a'",  # strings are outside this part's condition vocabulary
            "",
        ):
            try:
                _safe_eval_condition(hostile, {"amount": 1.0, "category_id": 1})
                raise AssertionError(f"hostile condition not rejected: {hostile!r}")
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
            raise AssertionError("hostile context object was evaluated")
        except ValueError:
            pass
        assert _Hostile.invoked is False, "hostile context object had a dunder invoked"

        # A hostile block-rule condition fails closed (does not apply, does not execute)
        with Session(engine) as session:
            session.add(
                PolicyRule(
                    name="hostile_rule",
                    condition="__import__('os').system('echo pwned')",
                    action="block",
                    message="should never fire",
                    category_id=1,
                )
            )
            session.commit()
        assert validate_policy(valid_expense) is None

        elapsed = time.monotonic() - start
        print(f"_selftest PASS ({elapsed:.3f}s)")
    finally:
        if engine is not None:
            engine.dispose()
        tmpdir.cleanup()


if __name__ == "__main__":
    _selftest()
