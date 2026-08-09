"""
approval_policy - Define approval policies with rules, validate contexts against them, and produce approval results.

### PART-META-JSON
{
  "name": "approval_policy",
  "layer": "approvals_workfl",
  "purpose": "Define approval policies with rules, validate contexts against them, and produce approval results.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "validate_policy(policy, context); apply_policy(policy, context).",
  "outputs": "ApprovalPolicy / PolicyRule rows; ValidationError lists; ApprovalResult decisions.",
  "files_created": [],
  "security_notes": "Authorization-adjacent: rule conditions are DB-sourced expression strings evaluated with a whitelisted AST interpreter (_safe_eval_condition), NOT eval(): only numeric/bool/str constants, context variable names, and/or/not, unary +/-, arithmetic (+ - * / // % ** with an exponent size cap), chained comparisons, and `in`/`not in` against list/tuple/set literals of constants are allowed; calls, attributes, subscripts and every other syntax element raise ValueError and the rule fails closed (evaluates False). apply_policy fails closed on validation errors. Policies gate money approvals downstream - protect policy-table writes with admin authorization.",
  "ai_usage": "Import what you need from `scrapyard.approvals_workfl.approval_policy`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.approvals_workfl.approval_policy import validate_policy",
  "import_path": "scrapyard.approvals_workfl.approval_policy"
}
### END-PART-META
"""
from __future__ import annotations

import ast
import logging
import operator
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, relationship, sessionmaker

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """Represents a validation error from a policy rule."""
    rule_id: Optional[int]
    message: str


@dataclass
class ApprovalResult:
    """Result of applying a policy to a context."""
    approved: bool
    violations: List[ValidationError] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)


class ApprovalPolicy(IntPKModel):
    """Defines an approval policy containing multiple rules."""
    __tablename__ = "approval_policies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    
    rules: Mapped[List["PolicyRule"]] = relationship(
        "PolicyRule",
        back_populates="policy",
        cascade="all, delete-orphan",
        lazy="selectin"
    )


class PolicyRule(IntPKModel):
    """Individual rule within an approval policy."""
    __tablename__ = "policy_rules"

    approval_policy_id: Mapped[int] = mapped_column(
        ForeignKey("approval_policies.id"), 
        nullable=False, 
        index=True
    )
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False, default="notify")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    policy: Mapped["ApprovalPolicy"] = relationship("ApprovalPolicy", back_populates="rules")


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
    """Whitelisted AST evaluation of a policy-rule condition (no eval()).

    Only permits: numeric/bool/str constants, names resolved from
    `context`, `and`/`or`/`not`, unary +/-, arithmetic (+ - * / // % **
    with a size guard on **), chained comparisons, and `in`/`not in`
    against list/tuple/set literals of constants. Every other syntax
    element (calls, attributes, subscripts, comprehensions, f-strings,
    ...) raises ValueError.
    """
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("Condition must be a non-empty string")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid condition syntax: {expression!r}") from exc

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
                        raise ValueError(f"Comparison {type(cmp_op).__name__} not allowed in conditions")
                    right = _eval(comparator)
                    if not fn(left, right):
                        return False
                left = right
            return True
        raise ValueError(f"Disallowed syntax in condition: {type(node).__name__}")

    return bool(_eval(tree))


def _evaluate_condition(condition: str, context: Dict[str, Any]) -> bool:
    """
    Evaluate a condition string against a context dictionary using the
    whitelisted AST evaluator. Fails closed (False) on disallowed syntax
    or evaluation errors.
    """
    try:
        return _safe_eval_condition(condition, context)
    except Exception as e:
        logger.error(f"Condition evaluation failed for '{condition}': {e}")
        return False


def validate_policy(policy: ApprovalPolicy, context: Dict[str, Any]) -> List[ValidationError]:
    """
    Validate a policy against a given context.
    Returns a list of validation errors for any rules that evaluate to False.
    """
    violations: List[ValidationError] = []
    
    if not policy.rules:
        logger.debug(f"Policy {policy.id} has no rules to validate")
        return violations
    
    # Evaluate rules in priority order
    sorted_rules = sorted(policy.rules, key=lambda r: r.priority)
    
    for rule in sorted_rules:
        try:
            result = _evaluate_condition(rule.condition, context)
            if not result:
                violations.append(
                    ValidationError(
                        rule_id=rule.id,
                        message=f"Rule condition failed: {rule.condition}"
                    )
                )
        except Exception as e:
            logger.exception(f"Unexpected error validating rule {rule.id}")
            violations.append(
                ValidationError(
                    rule_id=rule.id,
                    message=f"Validation exception: {str(e)}"
                )
            )
    
    return violations


def apply_policy(policy: ApprovalPolicy, context: Dict[str, Any]) -> ApprovalResult:
    """
    Apply a policy to a context, determining approval status and triggered actions.
    """
    violations = validate_policy(policy, context)
    
    if violations:
        return ApprovalResult(
            approved=False,
            violations=violations,
            actions=[]
        )
    
    # Collect actions from rules that match the context
    actions: List[str] = []
    sorted_rules = sorted(policy.rules, key=lambda r: r.priority)
    
    for rule in sorted_rules:
        try:
            if _evaluate_condition(rule.condition, context):
                actions.append(rule.action)
        except Exception:
            # Skip actions for rules that fail evaluation during application
            # (should not happen if validation passed, but defensive)
            continue
    
    return ApprovalResult(
        approved=True,
        violations=[],
        actions=actions
    )


def _selftest() -> None:
    """
    Offline self-test for the approval_policy module.
    Uses temporary SQLite database to verify functionality.
    """
    logger.info("Starting approval_policy selftest")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_approval_policy.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
        
        # Create all tables
        IntPKModel.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        try:
            # Test 1: Create and persist policy with rules
            policy = ApprovalPolicy(
                name="Expense Approval Policy",
                description="Validates expense reports based on amount and department"
            )
            session.add(policy)
            session.flush()  # Flush to get ID assigned
            
            rule1 = PolicyRule(
                policy=policy,
                condition="amount <= 1000",
                action="auto_approve",
                priority=1
            )
            rule2 = PolicyRule(
                policy=policy,
                condition="department in ['engineering', 'sales']",
                action="notify_manager",
                priority=2
            )
            session.add_all([rule1, rule2])
            session.commit()
            
            # Test 2: Retrieve policy and verify ORM mapping
            stmt = select(ApprovalPolicy).where(ApprovalPolicy.id == policy.id)
            retrieved_policy = session.execute(stmt).scalar_one()
            
            assert isinstance(retrieved_policy, ApprovalPolicy)
            assert retrieved_policy.name == "Expense Approval Policy"
            assert len(retrieved_policy.rules) == 2
            assert all(isinstance(r, PolicyRule) for r in retrieved_policy.rules)
            
            # Test 3: validate_policy identifies violations
            bad_context = {"amount": 5000, "department": "hr"}
            errors = validate_policy(retrieved_policy, bad_context)
            assert isinstance(errors, list)
            assert len(errors) >= 1
            assert all(isinstance(e, ValidationError) for e in errors)
            # Should fail the amount rule
            assert any("amount" in e.message for e in errors)
            
            # Test 4: validate_policy passes valid context
            good_context = {"amount": 500, "department": "engineering"}
            errors = validate_policy(retrieved_policy, good_context)
            assert len(errors) == 0
            
            # Test 5: apply_policy returns rejection for violations
            result_reject = apply_policy(retrieved_policy, bad_context)
            assert isinstance(result_reject, ApprovalResult)
            assert result_reject.approved is False
            assert len(result_reject.violations) > 0
            assert len(result_reject.actions) == 0
            
            # Test 6: apply_policy returns approval with actions
            result_approve = apply_policy(retrieved_policy, good_context)
            assert result_approve.approved is True
            assert len(result_approve.violations) == 0
            assert "auto_approve" in result_approve.actions
            assert "notify_manager" in result_approve.actions

            # Test 7: injection attempts raise ValueError in the safe
            # evaluator and fail closed through _evaluate_condition
            for hostile in [
                "().__class__.__mro__",
                "__import__('os').system('echo pwned')",
                "amount.__class__",
                "open('x')",
                "[x for x in (1,)]",
                "department in [open('x')]",
                "",
            ]:
                try:
                    _safe_eval_condition(hostile, good_context)
                    raise AssertionError(f"hostile condition not rejected: {hostile!r}")
                except ValueError:
                    pass
                assert _evaluate_condition(hostile, good_context) is False

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
            assert _evaluate_condition("x + 1 > 5", {"x": _Hostile()}) is False

            logger.info("approval_policy selftest completed successfully")
            
        except Exception:
            logger.exception("approval_policy selftest failed")
            raise
        finally:
            session.close()
            engine.dispose()
            # Cleanup temporary file
            try:
                os.unlink(db_path)
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    _selftest()
    print("approval_policy selftest OK")
