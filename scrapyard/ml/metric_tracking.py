"""
metric_tracking — Tracks and logs ML training metrics for analysis and monitoring, providing structured logging and integration with training and stopping logic.

### PART-META-JSON
{
  "name": "metric_tracking",
  "layer": "ml",
  "purpose": "Tracks and logs ML training metrics for analysis and monitoring, providing structured logging and integration with training and stopping logic.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "training_loop",
    "early_stopping"
  ],
  "inputs": "Public API: log_metric(name, value, step); reset_metrics(); get_metrics(); Metric(...); MetricTracker(...); MetricLogger(...).",
  "outputs": "Returns: log_metric -> None; reset_metrics -> None; get_metrics -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.metric_tracking`.",
  "example": "from scrapyard.ml.metric_tracking import *",
  "import_path": "scrapyard.ml.metric_tracking"
}
### END-PART-META
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

@dataclass
class Metric:
    name: str
    value: float
    step: int
    epoch: Optional[int] = None

class MetricTracker:
    def __init__(self):
        self.metrics: List[Metric] = []

    def log_metric(self, name: str, value: float, step: int, epoch: Optional[int] = None) -> None:
        metric = Metric(name=name, value=value, step=step, epoch=epoch)
        self.metrics.append(metric)

    def reset_metrics(self) -> None:
        self.metrics.clear()

    def get_metrics(self) -> Dict[str, Any]:
        return {metric.name: {"value": metric.value, "step": metric.step, "epoch": metric.epoch} for metric in self.metrics}

class MetricLogger:
    def __init__(self, tracker: MetricTracker):
        self.tracker = tracker

    def log(self, name: str, value: float, step: int) -> None:
        self.tracker.log_metric(name=name, value=value, step=step)

def log_metric(name: str, value: float, step: int) -> None:
    logger.info(f"Logging metric: {name}={value} at step {step}")

def reset_metrics() -> None:
    global tracker
    tracker.reset_metrics()

def get_metrics() -> Dict[str, Any]:
    return tracker.get_metrics()

# Self-test
def _selftest():
    global tracker

    # Initialize tracker and logger
    tracker = MetricTracker()
    logger = logging.getLogger(__name__)

    # Test log_metric
    tracker.log_metric("loss", 0.1, 1)
    tracker.log_metric("accuracy", 0.95, 1, epoch=1)
    assert len(tracker.metrics) == 2

    # Test reset_metrics
    tracker.reset_metrics()
    assert len(tracker.metrics) == 0

    # Test get_metrics
    tracker.log_metric("loss", 0.1, 1)
    metrics = tracker.get_metrics()
    assert "loss" in metrics and metrics["loss"]["value"] == 0.1 and metrics["loss"]["step"] == 1

    logger.info("Self-test passed.")

if __name__ == "__main__":
    _selftest()
