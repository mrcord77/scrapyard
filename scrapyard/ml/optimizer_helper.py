"""
optimizer_helper — Framework-free mock optimizer registry for tests and demos.

### PART-META-JSON
{
  "name": "optimizer_helper",
  "layer": "ml",
  "purpose": "Dependency-free MOCK optimizer framework: create_optimizer('SGD'|'Adam'|'RMSprop', params) builds lightweight stand-in optimizers over MockTensor parameters, and OptimizerHelper tracks state/step counts for mock training loops. HONEST LIMIT: these are NOT numerically real optimizers - _SGD/_Adam/_RMSprop all share one plain gradient-descent step (no momentum, moment estimates, or adaptive rates), and OptimizerHelper.step() applies a fixed +0.1*lr nudge. Use for exercising training-pipeline plumbing without installing torch; never for actual model training.",
  "status": "core",
  "dependencies": [],
  "inputs": "create_optimizer(name, {'params': [...], 'lr': ...}); OptimizerHelper(optimizer, params).step()/update_params().",
  "outputs": "Mock optimizer instances with param_groups/zero_grad/step; mutated MockTensor.data values; step_count in helper state.",
  "files_created": [],
  "security_notes": "Pure in-memory arithmetic on MockTensor dataclasses; no network, file, subprocess, or secret handling. The real risk is misuse, not exploitation: the optimizer names mimic torch.optim, so a careless import swap would silently produce garbage training - keep this part confined to tests/demos.",
  "ai_usage": "opt = create_optimizer('SGD', {'params': [MockTensor(1.0)], 'lr': 0.01}); OptimizerHelper(opt, params).step() to drive pipeline tests.",
  "example": "from scrapyard.ml.optimizer_helper import create_optimizer, OptimizerHelper",
  "import_path": "scrapyard.ml.optimizer_helper"
}
### END-PART-META
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional
import logging

logger = logging.getLogger(__name__)

PART_META_JSON = {
    "status": "core",
    "import_path": "scrapyard.ml.optimizer_helper",
    "layer": "ml",
    "name": "optimizer_helper",
    "description": "Provides reusable optimization algorithms for neural network training.",
}


@dataclass
class MockTensor:
    """Stand-in tensor used for mock training steps without external frameworks."""

    data: float
    grad: Optional[MockTensor] = None


class _BaseOptimizer:
    """Internal mock optimizer implementing the common optimizer interface."""

    def __init__(
        self,
        optimizer_type: str,
        parameters: List[MockTensor],
        **kwargs: Any,
    ) -> None:
        self.optimizer_type: str = optimizer_type
        self.defaults: Dict[str, Any] = kwargs
        self.param_groups: List[Dict[str, Any]] = [dict(kwargs)]
        self._parameters: List[MockTensor] = parameters

    def zero_grad(self) -> None:
        """Reset all parameter gradients to zero."""
        for param in self._parameters:
            if param.grad is not None:
                param.grad.data = 0.0
        logger.debug("%s zero_grad completed", self.optimizer_type)

    def step(self) -> None:
        """Perform a single optimization step."""
        lr = self.param_groups[0].get("lr", 0.01)
        for param in self._parameters:
            grad = param.grad.data if param.grad is not None else 0.0
            param.data -= lr * grad
        logger.debug("%s step completed", self.optimizer_type)


class _SGD(_BaseOptimizer):
    def __init__(
        self,
        parameters: List[MockTensor],
        lr: float = 0.01,
        momentum: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__("SGD", parameters, lr=lr, momentum=momentum, **kwargs)


class _Adam(_BaseOptimizer):
    def __init__(
        self,
        parameters: List[MockTensor],
        lr: float = 0.001,
        betas: Iterable[float] = (0.9, 0.999),
        eps: float = 1e-8,
        **kwargs: Any,
    ) -> None:
        betas = tuple(betas)
        super().__init__("Adam", parameters, lr=lr, betas=betas, eps=eps, **kwargs)


class _RMSprop(_BaseOptimizer):
    def __init__(
        self,
        parameters: List[MockTensor],
        lr: float = 0.01,
        alpha: float = 0.99,
        eps: float = 1e-8,
        **kwargs: Any,
    ) -> None:
        super().__init__("RMSprop", parameters, lr=lr, alpha=alpha, eps=eps, **kwargs)


Optimizer = _BaseOptimizer
Param = MockTensor

_OPTIMIZER_REGISTRY: Dict[str, type[_BaseOptimizer]] = {
    "SGD": _SGD,
    "ADAM": _Adam,
    "RMSPROP": _RMSprop,
}


def _coerce_parameters(raw: Any) -> List[MockTensor]:
    """Convert raw parameter values into a flat list of MockTensor objects."""
    if isinstance(raw, dict):
        raw = raw.get("params", [])

    result: List[MockTensor] = []
    for value in raw:
        if isinstance(value, MockTensor):
            result.append(value)
        else:
            result.append(MockTensor(float(value)))
    return result


def create_optimizer(optimizer_type: str, params: Mapping[str, Any]) -> Optimizer:
    """
    Dynamically create an optimizer of the requested type.

    :param optimizer_type: The type of optimizer (e.g., 'SGD', 'Adam', 'RMSprop').
    :param params: A mapping of hyperparameters, including a 'params' key.
    :return: An instance of the requested optimizer.
    :raises ValueError: If the optimizer type is not supported.
    """
    key = optimizer_type.upper()
    if key not in _OPTIMIZER_REGISTRY:
        raise ValueError(f"Unsupported optimizer type: {optimizer_type}")

    parameters = _coerce_parameters(params.get("params", params))
    optimizer_cls = _OPTIMIZER_REGISTRY[key]
    kwargs = {k: v for k, v in params.items() if k != "params"}

    optimizer = optimizer_cls(parameters, **kwargs)
    logger.debug("Created optimizer %s with %d parameter(s)", optimizer_type, len(parameters))
    return optimizer


@dataclass
class OptimizerHelper:
    """
    Tracks and manages optimizer state and parameters during mock training.

    :param optimizer: The optimizer instance driving updates.
    :param params: The parameters to track and update.
    """

    optimizer: Optimizer
    params: List[Any]
    state: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.state["optimizer"] = self.optimizer
        logger.debug("OptimizerHelper initialized")

    def update_params(self, new_params: List[Any]) -> None:
        """Replace the tracked parameters."""
        self.params = new_params
        logger.debug("Tracked parameters updated")

    def step(self) -> None:
        """
        Perform a mock training step, updating tracked parameters.
        """
        lr = 0.01
        if hasattr(self.optimizer, "param_groups") and isinstance(self.optimizer.param_groups, list):
            lr = self.optimizer.param_groups[0].get("lr", 0.01)

        for i, param in enumerate(self.params):
            if isinstance(param, MockTensor):
                grad = param.grad.data if param.grad is not None else 1.0
                param.data += 0.1 * lr * grad
            else:
                try:
                    self.params[i] += 0.1 * lr
                except TypeError:
                    logger.warning("Unsupported parameter type at index %d: %s", i, type(param))

        self.state.setdefault("step_count", 0)
        self.state["step_count"] += 1
        logger.debug("Training step %s completed", self.state["step_count"])


def _selftest() -> None:
    """Offline self-test for the optimizer helper module."""
    sgd_params = [MockTensor(1.0), MockTensor(2.0), MockTensor(3.0)]
    adam_params = [MockTensor(4.0), MockTensor(5.0), MockTensor(6.0)]

    sgd_optimizer = create_optimizer("SGD", {"params": sgd_params, "lr": 0.01, "momentum": 0.9})
    helper_sgd = OptimizerHelper(sgd_optimizer, sgd_params)
    helper_sgd.step()

    adam_optimizer = create_optimizer("Adam", {"params": adam_params, "lr": 0.001, "betas": (0.9, 0.999)})
    helper_adam = OptimizerHelper(adam_optimizer, adam_params)
    helper_adam.step()

    assert all(param.data > 1.0 for param in sgd_params)
    assert all(param.data > 4.0 for param in adam_params)
    assert helper_sgd.state["step_count"] == 1
    assert helper_adam.state["step_count"] == 1

    logger.info("optimizer_helper _selftest passed")


if __name__ == "__main__":
    _selftest()
