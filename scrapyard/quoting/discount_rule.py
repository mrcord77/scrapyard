"""
discount_rule — Rule-driven discount eligibility and application for quoting.

### PART-META-JSON
{
  "name": "discount_rule",
  "layer": "quoting",
  "purpose": "Persist discount rules (condition expression + percentage/fixed value, line_item or proposal scope) and evaluate/apply them to line items and proposals.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "DiscountRule dataclass (or DiscountRuleModel rows) with a condition expression over quantity/price_per_unit/total_amount; LineItem or Proposal targets.",
  "outputs": "check_eligibility -> bool; calculate_discount_amount -> Decimal; apply_discount mutates target prices and returns it.",
  "files_created": [],
  "security_notes": "Rule conditions are DB-sourced strings and are evaluated with a whitelisted AST interpreter (safe_eval_condition), NOT eval(): only literals, named context variables, and/or/not, arithmetic (+ - * / // % **) and chained comparisons are allowed; attribute access, calls, subscripts, comprehensions, f-strings and every other node type are rejected with ValueError, and exponents are size-capped to stop DoS via huge powers. Residual risks: rule VALUES are trusted (a rule author can still set a 100% discount), and discount math here is float-based - amounts are returned as Decimal but computed from floats, so keep authoritative money totals in integer cents downstream.",
  "ai_usage": "Import from `scrapyard.quoting.discount_rule`; create DiscountRuleModel rows, snapshot them into DiscountRule, then check_eligibility/apply_discount against LineItem/Proposal.",
  "example": "from scrapyard.quoting.discount_rule import DiscountRule, check_eligibility",
  "import_path": "scrapyard.quoting.discount_rule"
}
### END-PART-META
"""
from sqlalchemy import String, Float, Boolean, Text, DateTime, func, ForeignKey, Index, UniqueConstraint, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional, List, Union
import ast
import operator
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

STATUS = "core"

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


def safe_eval_condition(expression: str, context: dict) -> bool:
    """Evaluate a rule condition expression against a numeric context, safely.

    Only permits: numeric/bool constants, names resolved from `context`,
    `and`/`or`/`not`, unary minus, arithmetic (+ - * / // % **) and chained
    comparisons. Every other syntax element (calls, attributes, subscripts,
    lambdas, comprehensions, f-strings, ...) raises ValueError.
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
            if isinstance(node.value, bool) or isinstance(node.value, (int, float)):
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
            if isinstance(node.op, ast.Pow) and (
                abs(left) > _MAX_POW_OPERAND or abs(right) > 128
            ):
                raise ValueError("Exponentiation operands too large")
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


@dataclass(frozen=True)
class DiscountRule:
    id: int
    name: str
    condition: str
    discount_type: str
    value: float
    scope: str  # 'line_item' or 'proposal'
    active: bool


class Part(IntPKModel):
    __tablename__ = "parts"
    
    name: Mapped[str] = mapped_column(String(255), default="Unnamed Part")


class LineItem(IntPKModel):
    __tablename__ = "discount_rule_line_items"
    
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False, default=1)
    price_per_unit: Mapped[float] = mapped_column(nullable=False)
    proposal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("proposals.id"), nullable=True)
    proposal: Mapped[Optional["Proposal"]] = relationship(back_populates="line_items")


class Proposal(IntPKModel):
    __tablename__ = "proposals"
    
    line_items: Mapped[List["LineItem"]] = relationship(back_populates="proposal")


class DiscountRuleModel(IntPKModel):
    __tablename__ = "discount_rules"
    
    name: Mapped[str] = mapped_column(String(255), unique=True)
    condition: Mapped[str] = mapped_column(Text)
    discount_type: Mapped[str] = mapped_column(String(50))
    value: Mapped[float] = mapped_column(Float(precision=10))
    scope: Mapped[str] = mapped_column(String(50), default="line_item")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_onupdate=func.now()
    )


Index("ix_discount_rules_name", DiscountRuleModel.name)
UniqueConstraint(DiscountRuleModel.name, name="uq_discount_rules_name")


def check_eligibility(target: Union[LineItem, Proposal], rule: DiscountRule) -> bool:
    """Check if a line item or proposal is eligible for a discount rule."""
    if not rule.active:
        return False
        
    if rule.scope == "line_item":
        if not isinstance(target, LineItem):
            return False
        context = {
            "quantity": target.quantity,
            "price_per_unit": target.price_per_unit
        }
        return safe_eval_condition(rule.condition, context)
    elif rule.scope == "proposal":
        if not isinstance(target, Proposal):
            return False
        line_items = target.line_items
        total_qty = sum(li.quantity for li in line_items)
        total_amount = sum(li.quantity * li.price_per_unit for li in line_items)
        avg_price = total_amount / total_qty if total_qty > 0 else 0

        context = {
            "price_per_unit": avg_price,
            "quantity": total_qty,
            "total_amount": total_amount
        }
        return safe_eval_condition(rule.condition, context)
    else:
        raise ValueError(f"Invalid scope: {rule.scope}")


def calculate_discount_amount(target: Union[LineItem, Proposal], rule: DiscountRule) -> Decimal:
    """Calculate the discount amount for a line item or proposal."""
    if rule.scope == "line_item":
        if not isinstance(target, LineItem):
            raise ValueError("Expected LineItem for line_item scope rule")
        total_amount = target.quantity * target.price_per_unit
        if rule.discount_type == "percentage":
            discount = rule.value * total_amount
        elif rule.discount_type == "fixed_amount":
            discount = rule.value
        else:
            raise ValueError(f"Invalid discount type: {rule.discount_type}")
        return Decimal(str(discount))
    elif rule.scope == "proposal":
        if not isinstance(target, Proposal):
            raise ValueError("Expected Proposal for proposal scope rule")
        if rule.discount_type == "percentage":
            total = sum(li.quantity * li.price_per_unit for li in target.line_items)
            discount = rule.value * total
        elif rule.discount_type == "fixed_amount":
            discount = rule.value
        else:
            raise ValueError(f"Invalid discount type: {rule.discount_type}")
        return Decimal(str(discount))
    else:
        raise ValueError(f"Invalid scope: {rule.scope}")


def apply_discount(target: Union[LineItem, Proposal], rule: DiscountRule) -> Union[LineItem, Proposal]:
    """Apply a discount rule to a line item or proposal."""
    if check_eligibility(target, rule):
        discount_amount = float(calculate_discount_amount(target, rule))
        
        if rule.scope == "line_item" and isinstance(target, LineItem):
            if target.quantity > 0:
                discount_per_unit = discount_amount / target.quantity
                target.price_per_unit -= discount_per_unit
        elif rule.scope == "proposal" and isinstance(target, Proposal):
            total = sum(li.quantity * li.price_per_unit for li in target.line_items)
            if total > 0:
                for li in target.line_items:
                    li_share = (li.quantity * li.price_per_unit) / total
                    li_discount = discount_amount * li_share
                    if li.quantity > 0:
                        li.price_per_unit -= (li_discount / li.quantity)
    
    return target


def _selftest():
    # --- safe evaluator: allowed syntax works ---
    assert safe_eval_condition("quantity > 5", {"quantity": 6}) is True
    assert safe_eval_condition("quantity > 5", {"quantity": 5}) is False
    assert safe_eval_condition("1 < quantity <= 10 and price_per_unit * quantity >= 50",
                               {"quantity": 2, "price_per_unit": 30}) is True
    assert safe_eval_condition("not (quantity == 3) or price_per_unit < 0",
                               {"quantity": 4, "price_per_unit": 10}) is True
    assert safe_eval_condition("-quantity < 0", {"quantity": 1}) is True
    # --- safe evaluator: injection/abuse attempts are rejected ---
    for hostile in [
        "__import__('os').system('echo pwned')",
        "().__class__.__mro__",
        "[x for x in (1,)]",
        "quantity.__class__",
        "open('x')",
        "'a' 'b'",
        "quantity if True else 0",
        "unknown_var > 1",
        "(10**9)**(10**9)",
        "",
    ]:
        try:
            safe_eval_condition(hostile, {"quantity": 1})
            assert False, f"hostile expression not rejected: {hostile!r}"
        except ValueError:
            pass

    # EXPLOIT REGRESSION: a hostile context VALUE must not have its dunders
    # invoked. `quantity + 1` would call Hostile.__add__ if the value reached
    # the operator; _check_safe_value must reject it first.
    class _Hostile:
        invoked = False
        def __add__(self, other): _Hostile.invoked = True; return 0
        def __radd__(self, other): _Hostile.invoked = True; return 0
        def __gt__(self, other): _Hostile.invoked = True; return True
        def __bool__(self): _Hostile.invoked = True; return True
    try:
        safe_eval_condition("quantity + 1 > 5", {"quantity": _Hostile()})
        assert False, "hostile context object was evaluated"
    except ValueError:
        pass
    assert _Hostile.invoked is False, "hostile context object had a dunder invoked"

    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        db_path = os.path.join(temp_dir.name, "discount_rule_test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        IntPKModel.metadata.create_all(engine)
        
        with Session(engine) as session:
            part = Part(name="Test Part")
            session.add(part)
            session.commit()
            
            rule1_model = DiscountRuleModel(
                name="rule1", 
                condition="quantity > 5", 
                discount_type="percentage", 
                value=0.1, 
                scope="line_item"
            )
            rule2_model = DiscountRuleModel(
                name="rule2", 
                condition="price_per_unit < 100", 
                discount_type="fixed_amount", 
                value=10, 
                scope="proposal"
            )
            
            session.add_all([rule1_model, rule2_model])
            session.commit()
            
            rule1 = DiscountRule(
                id=rule1_model.id,
                name=rule1_model.name,
                condition=rule1_model.condition,
                discount_type=rule1_model.discount_type,
                value=rule1_model.value,
                scope=rule1_model.scope,
                active=rule1_model.active
            )
            
            rule2 = DiscountRule(
                id=rule2_model.id,
                name=rule2_model.name,
                condition=rule2_model.condition,
                discount_type=rule2_model.discount_type,
                value=rule2_model.value,
                scope=rule2_model.scope,
                active=rule2_model.active
            )
            
            line_item = LineItem(part_id=part.id, quantity=6, price_per_unit=50)
            proposal = Proposal(line_items=[line_item])
            line_item.proposal = proposal
            
            assert check_eligibility(line_item, rule1) == True
            assert check_eligibility(proposal, rule2) == True
            
            assert float(calculate_discount_amount(line_item, rule1)) == 0.1 * (6 * 50)
            assert float(calculate_discount_amount(proposal, rule2)) == 10
            
            apply_discount(line_item, rule1)
            assert line_item.price_per_unit == 45.0
            
    finally:
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
    print("discount_rule selftest OK")
