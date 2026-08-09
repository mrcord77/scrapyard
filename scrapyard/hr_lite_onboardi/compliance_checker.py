"""
compliance_checker — Evaluates HR onboarding compliance rules against staff context and records check results.

### PART-META-JSON
{
  "name": "compliance_checker",
  "layer": "hr_lite_onboardi",
  "purpose": "Defines compliance rules for HR onboarding workflows, evaluates them against per-staff context data, and persists timestamped check results for audit.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model"],
  "inputs": "Rule definitions, staff ids and context dicts; an engine bound via the module-level configuration.",
  "outputs": "ComplianceRule and ComplianceCheckResult rows; pass/fail evaluation results.",
  "files_created": [],
  "security_notes": "Check results may embed staff context details - avoid placing sensitive PII in rule context, and restrict read access to compliance_check_results. Rule conditions are DB-sourced expression strings evaluated with a whitelisted AST interpreter (_safe_eval_condition), NOT eval(): only numeric/bool/str constants, context variable names, and/or/not, unary +/-, arithmetic (+ - * / // % ** with an exponent size cap) and chained comparisons (== != < <= > >= is is-not) are allowed; calls, attributes, subscripts and every other syntax element raise ValueError and the rule fails closed (counts as non-compliant). No authorization checks: enforce who may define rules or run checks in the calling layer.",
  "ai_usage": "Import rule/check helpers from `scrapyard.hr_lite_onboardi.compliance_checker` after binding an engine.",
  "example": "from scrapyard.hr_lite_onboardi.compliance_checker import ComplianceRule",
  "import_path": "scrapyard.hr_lite_onboardi.compliance_checker"
}
### END-PART-META
"""
import ast
import logging
import operator
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

__part_meta__ = {
    "name": "compliance_checker",
    "layer": "hr_lite_onboardi",
    "version": "1.0.0",
    "description": "Compliance checker for HR onboarding workflows",
}

_engine: Optional[Engine] = None
_staff_contexts: Dict[int, Dict[str, Any]] = {}


class ComplianceRule(IntPKModel):
    __tablename__ = "compliance_rules"

    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ComplianceCheckResult(IntPKModel):
    __tablename__ = "compliance_check_results"

    staff_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("compliance_rules.id"), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


def configure_engine(url: Optional[str] = None) -> Engine:
    """Configure the database engine used by the compliance checker."""
    global _engine
    if url is None:
        url = os.environ.get("SCRAPYARD_DATABASE_URL", "sqlite:///compliance.db")
    _engine = create_engine(url, echo=False, future=True)
    return _engine


def _ensure_engine() -> Engine:
    if _engine is None:
        return configure_engine()
    return _engine


def _set_staff_context(staff_id: int, context: Dict[str, Any]) -> None:
    """Set evaluation context facts for a staff member (test helper)."""
    _staff_contexts[staff_id] = context


def _build_context(staff_id: int) -> Dict[str, Any]:
    context: Dict[str, Any] = {"staff_id": staff_id}
    context.update(_staff_contexts.get(staff_id, {}))
    return context


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
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
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
    """Whitelisted AST evaluation of a compliance-rule condition (no eval()).

    Only permits: numeric/bool/str constants, names resolved from
    `context`, `and`/`or`/`not`, unary +/-, arithmetic (+ - * / // % **
    with a size guard on **) and chained comparisons including `is` /
    `is not`. Every other syntax element (calls, attributes, subscripts,
    comprehensions, f-strings, ...) raises ValueError.
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
            if isinstance(node.value, _ALLOWED_CONST_TYPES):
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


def _evaluate_condition(condition: str, context: Dict[str, Any]) -> bool:
    condition = (condition or "").strip()
    if not condition:
        return True
    try:
        return _safe_eval_condition(condition, context)
    except Exception as exc:
        logger.warning("Condition evaluation failed: %s (%s)", condition, exc)
        return False


def _run_evaluation(staff_id: int, session: Session) -> tuple[bool, list[dict[str, Any]]]:
    context = _build_context(staff_id)
    rules = session.scalars(select(ComplianceRule).order_by(ComplianceRule.severity.desc())).all()

    rule_results: list[dict[str, Any]] = []
    all_pass = True

    for rule in rules:
        passed = _evaluate_condition(rule.condition, context)
        result = {
            "rule_id": rule.id,
            "rule_name": rule.rule_name,
            "description": rule.description,
            "severity": rule.severity,
            "condition": rule.condition,
            "passed": passed,
        }
        rule_results.append(result)
        if not passed:
            all_pass = False

    return all_pass, rule_results


def _persist_results(staff_id: int, rule_results: list[dict[str, Any]], session: Session) -> None:
    for result in rule_results:
        log_entry = ComplianceCheckResult(
            staff_id=staff_id,
            rule_id=result["rule_id"],
            passed=result["passed"],
            details=result,
        )
        session.add(log_entry)


def check_compliance(staff_id: int) -> bool:
    """Evaluate all compliance rules for a staff member and return the overall status."""
    engine = _ensure_engine()
    with Session(engine) as session:
        all_pass, rule_results = _run_evaluation(staff_id, session)
        _persist_results(staff_id, rule_results, session)
        session.commit()
    return all_pass


def generate_compliance_report(staff_id: int) -> dict[str, Any]:
    """Generate a structured, auditable compliance report for a staff member."""
    engine = _ensure_engine()
    with Session(engine) as session:
        all_pass, rule_results = _run_evaluation(staff_id, session)
        _persist_results(staff_id, rule_results, session)
        session.commit()

    passed_count = sum(1 for r in rule_results if r["passed"])
    failed_count = len(rule_results) - passed_count

    return {
        "staff_id": staff_id,
        "overall_status": all_pass,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_rules": len(rule_results),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "rule_results": rule_results,
        "failed_rules": [r for r in rule_results if not r["passed"]],
    }


def _selftest() -> bool:
    start = time.monotonic()
    global _engine

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = os.path.join(tmp_dir, "compliance_test.db")
        engine = configure_engine(f"sqlite:///{db_path}")
        IntPKModel.metadata.create_all(engine)

        try:
            _set_staff_context(
                1,
                {
                    "policy_signed": True,
                    "background_check": "passed",
                    "training_complete": True,
                },
            )
            _set_staff_context(
                2,
                {
                    "policy_signed": True,
                    "background_check": "passed",
                    "training_complete": False,
                },
            )

            with Session(engine) as session:
                session.add_all(
                    [
                        ComplianceRule(
                            rule_name="Policy Signed",
                            description="Staff must sign the company policy.",
                            condition="policy_signed is True",
                            severity=5,
                        ),
                        ComplianceRule(
                            rule_name="Background Check",
                            description="Staff background check must pass.",
                            condition="background_check == 'passed'",
                            severity=5,
                        ),
                        ComplianceRule(
                            rule_name="Training Complete",
                            description="Staff must complete onboarding training.",
                            condition="training_complete is True",
                            severity=3,
                        ),
                    ]
                )
                session.commit()

            assert check_compliance(1) is True
            assert check_compliance(2) is False

            report1 = generate_compliance_report(1)
            report2 = generate_compliance_report(2)

            assert isinstance(report1, dict)
            assert report1["staff_id"] == 1
            assert report1["overall_status"] is True
            assert report1["failed_count"] == 0
            assert report1["passed_count"] == 3

            assert report2["overall_status"] is False
            assert report2["failed_count"] == 1
            assert any(r["rule_name"] == "Training Complete" and not r["passed"] for r in report2["rule_results"])

            with Session(engine) as session:
                rule_count = session.scalar(select(func.count()).select_from(ComplianceRule))
                result_count = session.scalar(select(func.count()).select_from(ComplianceCheckResult))
                assert rule_count == 3
                assert result_count >= 6

            # Injection tests: the safe evaluator must raise ValueError, not execute
            hostile_context = {"policy_signed": True, "background_check": "passed"}
            for hostile in (
                "().__class__.__mro__",
                "__import__('os').system('echo pwned')",
                "policy_signed.__class__",
                "open('x')",
                "[x for x in (1,)]",
                "",
            ):
                try:
                    _safe_eval_condition(hostile, hostile_context)
                    raise AssertionError(f"hostile condition not rejected: {hostile!r}")
                except ValueError:
                    pass
                # _evaluate_condition fails closed on hostile non-empty input
                if hostile:
                    assert _evaluate_condition(hostile, hostile_context) is False

            # EXPLOIT REGRESSION: a hostile context VALUE must not have its
            # dunders invoked. `x + 1` would call Hostile.__add__ if the value
            # reached the operator; _check_safe_value rejects the non-primitive.
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

        finally:
            engine.dispose()
            _staff_contexts.clear()
            _engine = None

    elapsed = time.monotonic() - start
    assert elapsed < 20, f"Self-test took too long: {elapsed}s"
    return True


if __name__ == "__main__":
    _selftest()
