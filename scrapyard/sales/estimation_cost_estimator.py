"""
estimation_cost_estimator — Calculates total cost of an estimate based on task hours and rate cards. Provides modular, reusable cost estimation logic for pricing and quoting workflows.

### PART-META-JSON
{
  "name": "estimation_cost_estimator",
  "layer": "sales",
  "purpose": "Calculates total cost of an estimate based on task hours and rate cards. Provides modular, reusable cost estimation logic for pricing and quoting workflows.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: calculate_task_cost(task, rate_cards); aggregate_costs(costs); estimate_total_cost(tasks, rate_cards); Task(...); RateCardEntry(...).",
  "outputs": "Returns: calculate_task_cost -> float; aggregate_costs -> float; estimate_total_cost -> float.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.sales.estimation_cost_estimator`.",
  "example": "from scrapyard.sales.estimation_cost_estimator import *",
  "import_path": "scrapyard.sales.estimation_cost_estimator"
}
### END-PART-META
"""
from dataclasses import dataclass
from typing import List, Dict
import logging

_logger = logging.getLogger(__name__)

PART_META_JSON = {
    "name": "estimation_cost_estimator",
    "layer": "sales",
    "status": "core",
    "import_path": "scrapyard.sales.estimation_cost_estimator",
    "description": "Calculates total cost of an estimate based on task hours and rate cards."
}

@dataclass
class Task:
    id: int
    description: str
    hours: float

@dataclass
class RateCardEntry:
    task_type: str
    rate: float

def calculate_task_cost(task: Dict, rate_cards: Dict) -> float:
    """
    Calculate the cost for a single task based on its hours and matching rate card.
    
    :param task: A dictionary containing task details (description, hours).
    :param rate_cards: A dictionary of rate cards where keys are task types and values are rates.
    :return: The calculated cost for the task.
    """
    if not task or 'hours' not in task or 'type' not in task:
        return 0.0
    
    task_type = task['type']
    hours = task.get('hours', 0.0)
    
    rate = rate_cards.get(task_type, {}).get('rate', 0.0)
    if rate <= 0:
        _logger.warning(f"No valid rate found for task type: {task_type}")
        return 0.0
    
    return hours * rate

def aggregate_costs(costs: List[float]) -> float:
    """
    Aggregate costs from a list of individual task costs.
    
    :param costs: A list of cost values to be summed up.
    :return: The total aggregated cost.
    """
    if not costs:
        return 0.0
    return sum(costs)

def estimate_total_cost(tasks: List[Dict], rate_cards: Dict) -> float:
    """
    Estimate the total cost for a set of tasks based on their hours and matching rate cards.
    
    :param tasks: A list of task dictionaries containing details (description, hours).
    :param rate_cards: A dictionary of rate cards where keys are task types and values are rates.
    :return: The estimated total cost.
    """
    if not tasks or not rate_cards:
        return 0.0
    
    task_costs = [calculate_task_cost(task, rate_cards) for task in tasks]
    return aggregate_costs(task_costs)

def _selftest():
    """
    Self-test the module to ensure all functions work as expected.
    
    :return: None
    """
    # Test data
    tasks = [
        {"id": 1, "type": "Welding", "hours": 5.0},
        {"id": 2, "type": "Painting", "hours": 3.0}
    ]
    rate_cards = {
        "Welding": {"rate": 100.0},
        "Painting": {"rate": 75.0},
        "Assembly": {"rate": 80.0}
    }
    
    # Expected costs
    expected_costs = [calculate_task_cost(task, rate_cards) for task in tasks]
    total_expected_cost = aggregate_costs(expected_costs)
    
    # Run tests
    assert estimate_total_cost(tasks, rate_cards) == total_expected_cost
    assert calculate_task_cost({"type": "Welding", "hours": 5.0}, rate_cards) == expected_costs[0]
    assert calculate_task_cost({"type": "Unknown", "hours": 2.0}, rate_cards) == 0.0
    assert aggregate_costs([]) == 0.0
    
    _logger.info("Self-test passed successfully.")
    
if __name__ == "__main__":
    _selftest()
