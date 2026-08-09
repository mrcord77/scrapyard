"""
estimation_validator — Ensures estimates meet business rules and constraints by validating rate card compliance, task hours, and overall estimate structure. Acts as a gatekeeper for estimation pricing workflows.

### PART-META-JSON
{
  "name": "estimation_validator",
  "layer": "sales",
  "purpose": "Ensures estimates meet business rules and constraints by validating rate card compliance, task hours, and overall estimate structure. Acts as a gatekeeper for estimation pricing workflows.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: validate_estimate(estimate); check_rate_card_compliance(item); validate_task_hours(task); ValidationError(...); EstimateItemModel(...); EstimateTaskModel(...) (plus more).",
  "outputs": "Returns: validate_estimate -> List[ValidationError]; check_rate_card_compliance -> bool; validate_task_hours -> Optional[ValidationError].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.sales.estimation_validator`.",
  "example": "from scrapyard.sales.estimation_validator import *",
  "import_path": "scrapyard.sales.estimation_validator"
}
### END-PART-META
"""

from dataclasses import dataclass
from typing import Optional, List
import os, logging, sqlite3, tempfile

logger = logging.getLogger(__name__)

# Define custom error class for validation errors
class ValidationError(Exception):
    pass

@dataclass
class EstimateItemModel:
    name: str
    rate: float
    quantity: int
    total_cost: float

@dataclass
class EstimateTaskModel:
    task_id: int
    description: str
    hours: float
    is_labor: bool
    cost: float

@dataclass
class EstimateModel:
    estimate_id: int
    customer_name: str
    items: List[EstimateItemModel]
    tasks: List[EstimateTaskModel]

def validate_estimate(estimate: EstimateModel) -> List[ValidationError]:
    errors = []
    
    # Validate rate card compliance for each item
    for item in estimate.items:
        if not check_rate_card_compliance(item):
            errors.append(ValidationError(f"Item '{item.name}' does not comply with the rate card"))
    
    # Validate task hours against minimum and maximum thresholds
    for task in estimate.tasks:
        validation_error = validate_task_hours(task)
        if validation_error is not None:
            errors.append(validation_error)
    
    return errors

def check_rate_card_compliance(item: EstimateItemModel) -> bool:
    rate_card = {
        'labor': 50.0,
        'material': 10.0
    }
    
    if item.name.startswith('Labor'):
        return item.rate == rate_card['labor']
    elif item.name.startswith('Material'):
        return item.rate == rate_card['material']
    else:
        return False

def validate_task_hours(task: EstimateTaskModel) -> Optional[ValidationError]:
    min_hours = 1.0
    max_hours = 24.0
    
    if task.hours < min_hours or task.hours > max_hours:
        return ValidationError(f"Task '{task.task_id}' has invalid hours ({task.hours}) - must be between {min_hours} and {max_hours}")
    
    return None

def _selftest() -> bool:
    """Offline self-test: a rate-card-compliant, in-range estimate passes with zero
    errors; out-of-range task hours and rate-card violations are each rejected with
    a descriptive error."""
    # 1) Fully compliant estimate: Labor@50, Material@10, hours within [1, 24].
    good = EstimateModel(
        estimate_id=1, customer_name="Acme",
        items=[EstimateItemModel(name="Labor Service", rate=50.0, quantity=2, total_cost=100.0),
               EstimateItemModel(name="Material A", rate=10.0, quantity=3, total_cost=30.0)],
        tasks=[EstimateTaskModel(task_id=1, description="t1", hours=8.5, is_labor=True, cost=425.0),
               EstimateTaskModel(task_id=2, description="t2", hours=16.0, is_labor=False, cost=320.0)],
    )
    assert validate_estimate(good) == [], [str(e) for e in validate_estimate(good)]

    # 2) Out-of-range hours (30 > max 24) is rejected via validate_task_hours.
    over = EstimateTaskModel(task_id=9, description="marathon", hours=30.0, is_labor=True, cost=0.0)
    err = validate_task_hours(over)
    assert err is not None and "invalid hours" in str(err), err
    # And zero hours (below min 1) is likewise rejected.
    assert validate_task_hours(
        EstimateTaskModel(task_id=10, description="none", hours=0.0, is_labor=True, cost=0.0)) is not None
    # In-range hours pass (returns None).
    assert validate_task_hours(
        EstimateTaskModel(task_id=11, description="ok", hours=5.0, is_labor=True, cost=0.0)) is None

    # 3) Rate-card violation: Labor item priced off the $50 card is non-compliant.
    assert check_rate_card_compliance(
        EstimateItemModel(name="Labor Overpriced", rate=99.0, quantity=1, total_cost=99.0)) is False
    assert check_rate_card_compliance(
        EstimateItemModel(name="Labor Service", rate=50.0, quantity=1, total_cost=50.0)) is True

    # 4) Negative/adversarial: an item whose name matches no rate-card category is
    #    non-compliant (fails closed rather than defaulting to allowed).
    assert check_rate_card_compliance(
        EstimateItemModel(name="Mystery Fee", rate=1.0, quantity=1, total_cost=1.0)) is False

    # 5) End-to-end: an estimate mixing a bad rate and bad hours surfaces BOTH errors.
    bad = EstimateModel(
        estimate_id=2, customer_name="Bad",
        items=[EstimateItemModel(name="Labor Service", rate=75.0, quantity=1, total_cost=75.0)],
        tasks=[EstimateTaskModel(task_id=3, description="too long", hours=99.0, is_labor=True, cost=0.0)],
    )
    errors = validate_estimate(bad)
    assert len(errors) == 2, [str(e) for e in errors]

    print("estimation_validator selftest: PASS")
    return True

if __name__ == "__main__":
    if not _selftest():
        raise SystemExit(1)
