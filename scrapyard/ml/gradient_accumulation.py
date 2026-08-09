"""
gradient_accumulation — Accumulate gradients across micro-batches for large effective batch sizes.

### PART-META-JSON
{
  "name": "gradient_accumulation",
  "layer": "ml",
  "purpose": "PyTorch gradient accumulation: GradientAccumulator scales each micro-batch loss by 1/accumulation_steps, backpropagates, and automatically clips (element-wise clamp to +/-10) and steps the optimizer once the configured number of micro-batches has accumulated, simulating a larger batch size under limited GPU memory.",
  "status": "core",
  "dependencies": [
    "torch"
  ],
  "inputs": "GradientAccumulator(model: torch.nn.Module, accumulation_steps: int, optimizer=None); set_optimizer(); accumulate(loss: torch.Tensor) per micro-batch.",
  "outputs": "Optimizer parameter updates every accumulation_steps micro-batches; internal counter reset afterwards.",
  "files_created": [],
  "security_notes": "Pure in-process tensor math on caller-supplied model/optimizer - no network, file, or secret handling (the selftest's temp SQLite log is test-only). Behavioral caveats that matter more than security: gradient clipping is a hard-coded element-wise clamp to +/-10 (not norm clipping) applied on every step, which silently alters training dynamics; accumulate() zeroes gradients at the start of each cycle, so do not interleave other backward passes on the same optimizer mid-cycle.",
  "ai_usage": "acc = GradientAccumulator(model, accumulation_steps=8, optimizer=opt); inside the loop: acc.accumulate(loss_fn(model(x), y)).",
  "example": "from scrapyard.ml.gradient_accumulation import GradientAccumulator",
  "import_path": "scrapyard.ml.gradient_accumulation"
}
### END-PART-META
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["GradientAccumulator"]

PART_META = {
    "name": "gradient_accumulation",
    "layer": "ml",
}
__part_meta__ = json.dumps(PART_META)


class GradientAccumulator:
    """
    Accumulates gradients across multiple micro-batches to simulate a larger
    effective batch size when GPU/TPU memory is limited.
    """

    def __init__(
        self,
        model: Any,
        accumulation_steps: int,
        optimizer: Optional[Any] = None,
    ) -> None:
        import torch

        if not isinstance(model, torch.nn.Module):
            raise TypeError("model must be a torch.nn.Module")
        if not isinstance(accumulation_steps, int) or accumulation_steps <= 0:
            raise ValueError("accumulation_steps must be a positive integer")

        self.model = model
        self.accumulation_steps = accumulation_steps
        self.optimizer = optimizer
        self._accumulated: int = 0

    def set_optimizer(self, optimizer: Any) -> None:
        """Attach an optimizer after construction."""
        self.optimizer = optimizer

    def zero_grad(self) -> None:
        """Explicitly zero the optimizer gradients."""
        if self.optimizer is None:
            raise ValueError("Optimizer not set.")
        self.optimizer.zero_grad()
        logger.debug("Optimizer gradients zeroed.")

    def accumulate(self, loss: Any) -> None:
        """
        Scale ``loss``, back-propagate, and count the micro-batch.

        When ``accumulation_steps`` micro-batches have been processed,
        :meth:`step` is called automatically.
        """
        import torch

        if not isinstance(loss, torch.Tensor):
            raise TypeError("loss must be a torch.Tensor")
        if self.optimizer is None:
            raise ValueError(
                "Optimizer not set. Please call `set_optimizer` or pass "
                "optimizer to `__init__` before accumulating gradients."
            )

        # Start a fresh accumulation cycle.
        if self._accumulated == 0:
            self.optimizer.zero_grad()
            logger.debug("Zeroed gradients for a new accumulation cycle.")

        scaled_loss = loss / self.accumulation_steps
        scaled_loss.backward()
        self._accumulated += 1

        logger.info(
            "Accumulated gradient step %d/%d",
            self._accumulated,
            self.accumulation_steps,
        )

        if self._accumulated == self.accumulation_steps:
            self.step()

    def step(self) -> None:
        """
        Clip accumulated gradients and perform an optimizer update, then reset
        the accumulation counter.
        """
        if self.optimizer is None:
            raise ValueError("Optimizer not set.")

        for param in self.model.parameters():
            if param.grad is not None:
                param.grad.data.clamp_(-10, 10)

        self.optimizer.step()
        logger.info(
            "Optimizer step executed after %d accumulation steps.",
            self.accumulation_steps,
        )
        self.reset()

    def reset(self) -> None:
        """Reset the internal accumulation counter and free gradient buffers."""
        self._accumulated = 0
        if self.optimizer is not None:
            self.optimizer.zero_grad()
        logger.debug("Gradient accumulator reset.")


def _selftest() -> None:
    """Offline validation of the gradient accumulation utilities."""
    logging.basicConfig(level=logging.DEBUG)

    import torch

    class SimpleModel(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.fc = torch.nn.Linear(10, 1)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.fc(x)

    model = SimpleModel()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    accumulator = GradientAccumulator(model, accumulation_steps=2)
    accumulator.set_optimizer(optimizer)

    x = torch.randn(4, 10)
    y = torch.randn(4, 1)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "gradient_accum.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "CREATE TABLE events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "event TEXT NOT NULL, "
                "step_number INTEGER NOT NULL"
                ")"
            )

            initial_weight = model.fc.weight.detach().clone()

            # Run enough micro-batches to complete full accumulation cycles.
            for step_number in range(1, 5):
                output = model(x)
                loss = (output - y).pow(2).mean()
                accumulator.accumulate(loss)

                conn.execute(
                    "INSERT INTO events (event, step_number) VALUES (?, ?)",
                    ("accumulate", step_number),
                )
                conn.commit()

            # After 4 micro-batches with accumulation_steps=2, the counter
            # should be reset to 0.
            assert accumulator._accumulated == 0, "Accumulation counter not reset."

            # Weights must have been updated by the optimizer.
            assert not torch.equal(model.fc.weight, initial_weight), "Weights were not updated."

            # Verify the SQLite tracking table captured every accumulate call.
            row_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            assert row_count == 4, f"Expected 4 logged events, got {row_count}."

            logger.debug("Gradient accumulation self-test passed.")
        finally:
            conn.close()


if __name__ == "__main__":
    _selftest()
