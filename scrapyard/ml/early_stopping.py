"""
early_stopping — early stopping

### PART-META-JSON
{
  "name": "early_stopping",
  "layer": "ml",
  "purpose": "early stopping",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: EarlyStopping(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.early_stopping`.",
  "example": "from scrapyard.ml.early_stopping import *",
  "import_path": "scrapyard.ml.early_stopping"
}
### END-PART-META
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import logging
import tempfile

logger = logging.getLogger(__name__)


@dataclass
class EarlyStopping:
    patience: int
    min_delta: float
    mode: str  # 'min' or 'max'
    metric_name: str
    current_value: Optional[float] = None
    best_value: Optional[float] = field(default=None, init=False)
    best_step: Optional[int] = field(default=None, init=False)
    step_count: int = field(default=0, init=False)
    _last_step: Optional[int] = field(default=None, init=False)

    def __post_init__(self):
        if self.mode not in ('min', 'max'):
            raise ValueError("Mode must be either 'min' or 'max'")
        self.reset()

    def update(self, current_value: float, step: int) -> bool:
        """Update early stopping state with new metric value.
        
        Returns True if training should stop, False otherwise.
        """
        self.current_value = current_value
        self._last_step = step
        
        improved = False
        if self.best_value is None:
            improved = True
        elif self.mode == 'min':
            if current_value < self.best_value - self.min_delta:
                improved = True
        else:  # mode == 'max'
            if current_value > self.best_value + self.min_delta:
                improved = True
        
        if improved:
            self.best_value = current_value
            self.best_step = step
            self.step_count = 0
            logger.debug(f"Improvement at step {step}: {self.metric_name}={current_value}")
        else:
            self.step_count += 1
            logger.debug(f"No improvement at step {step}: {self.metric_name}={current_value}, "
                        f"best={self.best_value}, patience_count={self.step_count}")
        
        return self.should_stop()

    def should_stop(self) -> bool:
        """Check if training should stop based on patience."""
        return self.step_count >= self.patience

    def reset(self):
        """Reset the early stopping state."""
        self.best_value = None
        self.best_step = None
        self.step_count = 0
        self._last_step = None
        self.current_value = None

    def get_best_value(self) -> Optional[float]:
        """Get the best metric value seen so far."""
        return self.best_value

    def get_best_step(self) -> Optional[int]:
        """Get the step at which the best metric value was seen."""
        return self.best_step

    def get_state(self) -> Dict[str, Any]:
        """Get serializable state for checkpointing."""
        return {
            'patience': self.patience,
            'min_delta': self.min_delta,
            'mode': self.mode,
            'metric_name': self.metric_name,
            'current_value': self.current_value,
            'best_value': self.best_value,
            'best_step': self.best_step,
            'step_count': self.step_count,
            '_last_step': self._last_step,
        }

    def load_state(self, state: Dict[str, Any]):
        """Load state from dictionary."""
        self.patience = state['patience']
        self.min_delta = state['min_delta']
        self.mode = state['mode']
        self.metric_name = state['metric_name']
        self.current_value = state['current_value']
        self.best_value = state['best_value']
        self.best_step = state['best_step']
        self.step_count = state['step_count']
        self._last_step = state['_last_step']


def _selftest():
    """Self-test for EarlyStopping."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Test 1: EarlyStopping triggers stop after patience steps with no improvement (min mode)
        es = EarlyStopping(patience=3, min_delta=0.01, mode='min', metric_name='loss')
        assert es.update(1.0, step=0) == False  # First value, best set, improved
        assert es.update(0.9, step=1) == False  # Improvement (0.9 < 1.0-0.01)
        assert es.update(0.8, step=2) == False  # Improvement (0.8 < 0.9-0.01)
        assert es.update(0.8, step=3) == False  # No improvement, count=1
        assert es.update(0.8, step=4) == False  # No improvement, count=2
        assert es.update(0.8, step=5) == True   # No improvement, count=3 >= patience(3) -> stop
        
        # Test 2: Max mode with min_delta
        es_max = EarlyStopping(patience=2, min_delta=0.1, mode='max', metric_name='accuracy')
        assert es_max.update(0.5, step=0) == False   # First value, best=0.5
        assert es_max.update(0.61, step=1) == False  # Improvement (0.61 > 0.5+0.1), best=0.61
        assert es_max.update(0.65, step=2) == False  # No improvement (0.65 not > 0.61+0.1), count=1
        assert es_max.update(0.7, step=3) == True    # No improvement (0.7 not > 0.61+0.1=0.71), count=2 -> stop
        
        # Test 3: Tracks best value and step correctly
        es3 = EarlyStopping(patience=5, min_delta=0.01, mode='min', metric_name='loss')
        es3.update(1.0, step=10)
        es3.update(0.5, step=20)
        es3.update(0.6, step=30)  # no improvement
        assert es3.get_best_value() == 0.5
        assert es3.get_best_step() == 20
        
        # Test 4: Reset reinitializes properly
        es3.reset()
        assert es3.get_best_value() is None
        assert es3.get_best_step() is None
        assert es3.should_stop() == False
        assert es3.step_count == 0
        
        # Test 5: Returns False for should_stop() when improvement is detected
        es4 = EarlyStopping(patience=2, min_delta=0.01, mode='min', metric_name='loss')
        es4.update(1.0, step=0)
        result = es4.update(0.5, step=1)  # Big improvement
        assert result == False  # Should not stop because we improved
        assert es4.should_stop() == False
        
        # Test 6: State serialization and loading
        es5 = EarlyStopping(patience=3, min_delta=0.01, mode='min', metric_name='loss')
        es5.update(0.5, step=5)
        es5.update(0.6, step=6)  # no improvement, count=1
        
        state = es5.get_state()
        assert state['best_value'] == 0.5
        assert state['best_step'] == 5
        assert state['step_count'] == 1
        assert state['mode'] == 'min'
        
        # Create new instance with different initial values and load state
        es6 = EarlyStopping(patience=99, min_delta=0.99, mode='max', metric_name='different')
        es6.load_state(state)
        assert es6.patience == 3
        assert es6.min_delta == 0.01
        assert es6.mode == 'min'
        assert es6.metric_name == 'loss'
        assert es6.best_value == 0.5
        assert es6.best_step == 5
        assert es6.step_count == 1
        
        # Test 7: ValueError on invalid mode
        try:
            EarlyStopping(patience=1, min_delta=0.1, mode='invalid', metric_name='x')
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "min" in str(e).lower() or "max" in str(e).lower()
        
        # Test 8: min_delta logic - small improvements below threshold don't count
        es7 = EarlyStopping(patience=1, min_delta=0.1, mode='min', metric_name='loss')
        es7.update(1.0, step=0)  # best=1.0
        result = es7.update(0.95, step=1)  # 0.95 is not < 1.0-0.1 (0.9), so no improvement
        assert result == True  # count=1 >= patience=1 -> stop
        assert es7.get_best_value() == 1.0  # best should remain 1.0
        
        print("_selftest passed")


if __name__ == "__main__":
    _selftest()
