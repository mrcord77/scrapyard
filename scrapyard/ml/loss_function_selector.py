"""
loss_function_selector — The `loss_function_selector` module provides a flexible and extensible mechanism to choose appropriate loss functions for machine learning tasks, ensuring compatibility with model architectures and tr

### PART-META-JSON
{
  "name": "loss_function_selector",
  "layer": "ml",
  "purpose": "The `loss_function_selector` module provides a flexible and extensible mechanism to choose appropriate loss functions for machine learning tasks, ensuring compatibility with model architectures and tr",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: LossFunctionSelector(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.loss_function_selector`.",
  "example": "from scrapyard.ml.loss_function_selector import *",
  "import_path": "scrapyard.ml.loss_function_selector"
}
### END-PART-META
"""

import logging
import os
import sqlite3
import tempfile
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class LossFunctionSelector:
    """
    A class to handle the selection of appropriate loss functions based on task type and model architecture.
    """

    LOSS_FUNCTIONS: Dict[str, Dict[str, Callable[..., Any]]] = {
        "classification": {"binary": lambda y_true, y_pred: -y_true * y_pred.log() - (1 - y_true) * (1 - y_pred).log()},
        "regression": {"mean_squared_error": lambda y_true, y_pred: (y_true - y_pred) ** 2 / 2},
    }

    def __init__(self) -> None:
        self.custom_losses: Dict[str, Dict[str, Callable[..., Any]]] = {}

    @staticmethod
    def _get_task_type(task_type: str) -> str:
        task_type = task_type.lower().strip()
        return task_type

    @staticmethod
    def _get_model_architecture(model_architecture: str) -> str:
        model_architecture = model_architecture.lower().strip()
        return model_architecture

    def register_loss_function(self, task_type: str, loss_name: str, loss_function: Callable[..., Any]) -> None:
        """
        Register a custom loss function.
        """
        task_type = self._get_task_type(task_type)
        self.custom_losses.setdefault(task_type, {})[loss_name] = loss_function
        logger.info(f"Registered custom loss function {loss_name} for task type {task_type}")

    def select_loss_function(
        self,
        task_type: str,
        model_architecture: str,
        custom_losses: Optional[Dict[str, Callable[..., Any]]] = None,
    ) -> Callable[..., Any]:
        """
        Select an appropriate loss function based on the given task type and model architecture.
        """
        task_type = self._get_task_type(task_type)
        model_architecture = self._get_model_architecture(model_architecture)

        # Check if a custom loss is provided in `custom_losses` parameter
        if custom_losses and task_type in custom_losses:
            logger.info(f"Using custom loss function from parameter for {task_type}")
            return custom_losses[task_type]

        # Check the registered custom losses
        if task_type in self.custom_losses:
            selected_losses = self.custom_losses[task_type]
            if model_architecture in selected_losses:
                logger.info(f"Using registered custom loss for {task_type}/{model_architecture}")
                return selected_losses[model_architecture]
            elif selected_losses:
                # Fallback to first available custom loss for this task type
                first_loss = next(iter(selected_losses.values()))
                logger.info(f"Using fallback custom loss for {task_type}")
                return first_loss

        # Fallback to predefined loss functions
        if task_type in self.LOSS_FUNCTIONS:
            if model_architecture in self.LOSS_FUNCTIONS[task_type]:
                logger.info(f"Using predefined loss for {task_type}/{model_architecture}")
                return self.LOSS_FUNCTIONS[task_type][model_architecture]

        logger.warning(f"No suitable loss function found for {task_type} and {model_architecture}, using default")

        # Default to mean squared error
        return self.LOSS_FUNCTIONS["regression"]["mean_squared_error"]


def _selftest() -> None:
    """
    Self-test the LossFunctionSelector.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_loss_selector.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE selection_log (
                id INTEGER PRIMARY KEY,
                task_type TEXT,
                architecture TEXT,
                loss_function TEXT,
                timestamp REAL
            )
        """
        )
        conn.commit()

        selector = LossFunctionSelector()

        # Test common task-architecture pairs
        loss_cls = selector.select_loss_function("classification", "binary")
        assert loss_cls == selector.LOSS_FUNCTIONS["classification"]["binary"]
        cursor.execute(
            "INSERT INTO selection_log (task_type, architecture, loss_function, timestamp) VALUES (?, ?, ?, ?)",
            ("classification", "binary", "binary_cross_entropy", 0.0),
        )
        conn.commit()

        loss_reg = selector.select_loss_function("regression", "mean_squared_error")
        assert loss_reg == selector.LOSS_FUNCTIONS["regression"]["mean_squared_error"]

        # Register custom


if __name__ == "__main__":
    _selftest()
