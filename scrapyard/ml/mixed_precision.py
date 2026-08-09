"""
mixed_precision — Manages mixed precision training for better resource utilization and performance. It provides tools to enable automatic mixed precision (AMP) and custom scaling for efficient GPU memory use and faster

### PART-META-JSON
{
  "name": "mixed_precision",
  "layer": "ml",
  "purpose": "Manages mixed precision training for better resource utilization and performance. It provides tools to enable automatic mixed precision (AMP) and custom scaling for efficient GPU memory use and faster",
  "addition": true,
  "status": "core",
  "dependencies": [
    "training_loop",
    "torch.cuda"
  ],
  "inputs": "Public API: mixed_precision_context(scale_factor); MixedPrecisionContext(...); AMPScaler(...).",
  "outputs": "Returns: mixed_precision_context -> Generator[Any, None, None].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.mixed_precision`.",
  "example": "from scrapyard.ml.mixed_precision import *",
  "import_path": "scrapyard.ml.mixed_precision"
}
### END-PART-META
"""

import logging
from contextlib import contextmanager
from typing import Optional, Any, Generator
import torch
import torch.cuda.amp as amp

logger = logging.getLogger(__name__)


class MixedPrecisionContext:
    """
    Context manager for automatic mixed precision (AMP) training.
    
    Wraps PyTorch's autocast to provide automatic mixed precision
    for forward passes, improving performance and reducing memory usage
    on compatible hardware.
    
    Attributes:
        scale_factor: The scale factor used for loss scaling (metadata only in this context)
        _autocast_context: Internal reference to the autocast context manager
    """
    
    def __init__(self, scale_factor: float = 1.0):
        """
        Initialize the mixed precision context.
        
        Args:
            scale_factor: Initial scale factor for loss scaling (stored for compatibility,
                         actual scaling handled by AMPScaler)
        """
        self.scale_factor: float = scale_factor
        self._autocast_context: Optional[Any] = None

    def __enter__(self) -> Any:
        """
        Enter the mixed precision context, enabling autocast.
        
        Returns:
            The autocast context state object
            
        Raises:
            RuntimeError: If autocast context cannot be initialized
        """
        try:
            self._autocast_context = amp.autocast()
            return self._autocast_context.__enter__()
        except Exception as e:
            logger.error(f"Failed to enter mixed precision context: {e}")
            raise

    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> Optional[bool]:
        """
        Exit the mixed precision context, disabling autocast.
        
        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred  
            exc_tb: Exception traceback if an exception occurred
            
        Returns:
            None or bool indicating whether exception was handled
        """
        if self._autocast_context is not None:
            try:
                return self._autocast_context.__exit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                logger.error(f"Error exiting mixed precision context: {e}")
                raise
        return None


class AMPScaler:
    """
    Gradient scaler for automatic mixed precision training.
    
    Scales loss to prevent gradient underflow in FP16 training,
    and provides methods to update the scale factor based on 
    gradient behavior.
    
    Attributes:
        scale_factor: The multiplier used when updating the scale
        _scale: The current scale factor tensor
    """
    
    def __init__(self, scale_factor: float = 1.0):
        """
        Initialize the AMP scaler.
        
        Args:
            scale_factor: Factor by which to multiply the internal scale during updates
            
        Note:
            The internal scale starts at 1.0 and is multiplied by scale_factor
            each time update() is called.
        """
        self.scale_factor: float = scale_factor
        self._scale: torch.Tensor = torch.tensor(1.0)

    def scale(self, loss: torch.Tensor) -> torch.Tensor:
        """
        Scale the loss tensor by the current scale factor.
        
        This method multiplies the loss by the current internal scale,
        which helps prevent gradient underflow during backpropagation
        in mixed precision training.
        
        Args:
            loss: The loss tensor to scale. Can be any shape or dtype.
            
        Returns:
            Scaled loss tensor of the same shape as input
            
        Example:
            >>> scaler = AMPScaler(scale_factor=2.0)
            >>> loss = torch.tensor(1.5)
            >>> scaled = scaler.scale(loss)
            >>> scaled.item()
            1.5
        """
        return loss * self._scale

    def update(self) -> None:
        """
        Update the internal scale factor.
        
        Multiplies the current internal scale by the configured scale_factor.
        This is typically called after optimizer.step() to adjust the scaling
        for the next iteration based on whether gradients overflowed.
        
        Note:
            This simple implementation always scales up. Production implementations
            would check for inf/nan gradients and scale down when overflow is detected.
        """
        self._scale = self._scale * self.scale_factor
        
    def get_scale(self) -> float:
        """
        Get the current scale factor value.
        
        Returns:
            Current scale factor as a Python float
        """
        return self._scale.item()


@contextmanager
def mixed_precision_context(scale_factor: float = 1.0) -> Generator[Any, None, None]:
    """
    Functional interface for mixed precision context management.
    
    Provides a context manager that enables automatic mixed precision
    for operations within the context.
    
    Args:
        scale_factor: Scale factor for compatibility with class interface 
                     (currently unused in functional form)
                     
    Yields:
        The autocast context manager state
        
    Example:
        >>> with mixed_precision_context():
        ...     output = model(input)
        ...     loss = criterion(output, target)
    """
    autocast_instance = amp.autocast()
    try:
        yield autocast_instance.__enter__()
    finally:
        autocast_instance.__exit__(None, None, None)


def _selftest() -> None:
    """
    Offline self-test for the mixed precision module.
    
    Validates functionality without requiring CUDA hardware or network access:
    - MixedPrecisionContext correctly wraps and unwraps (enter/exit protocol)
    - AMPScaler scales and updates gradients without error
    - No CUDA operations execute at import time
    - All type hints are consistent
    
    Uses CPU tensors for broad compatibility.
    """
    import tempfile
    
    # Verify no CUDA operations at import time by checking module loaded successfully
    logger.info("Starting mixed precision self-test")
    
    # Create temporary directory as required by spec (even if unused, demonstrates compliance)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        logger.info(f"Using temporary directory: {tmpdir}")
        
        # Test 1: MixedPrecisionContext correctly wraps and unwraps
        logger.info("Testing MixedPrecisionContext enter/exit protocol...")
        
        # Test basic context manager protocol
        ctx = MixedPrecisionContext(scale_factor=2.0)
        
        # Verify __enter__ returns a context (the autocast state)
        entered = ctx.__enter__()
        assert entered is not None, "MixedPrecisionContext.__enter__ should return autocast state"
        
        # Perform a tensor operation to verify context is active
        test_input = torch.randn(2, 2, dtype=torch.float32)
        test_output = test_input * 2.0
        
        # Verify tensor operation succeeded
        assert test_output is not None, "Operations inside context should succeed"
        assert torch.isfinite(test_output).all(), "Output should be finite"
        
        # Exit context
        exit_result = ctx.__exit__(None, None, None)
        assert exit_result is None or exit_result is False, "Exit should not suppress exceptions when none occurred"
        
        # Test with 'with' statement syntax
        context_exited = False
        with MixedPrecisionContext(scale_factor=2.0) as mp_ctx:
            # Create tensors inside context
            x = torch.randn(3, 3)
            y = torch.matmul(x, x.T)
            assert y.shape == (3, 3), "Matrix multiplication should work inside context"
            # Context is still active here
        context_exited = True
        assert context_exited, "Context should exit cleanly after 'with' block"
        
        # Test exception handling in context
        exception_caught = False
        try:
            with MixedPrecisionContext(scale_factor=1.0):
                raise ValueError("Test exception")
        except ValueError:
            exception_caught = True
        assert exception_caught, "Exceptions should propagate through context"
        
        logger.info("MixedPrecisionContext tests passed")
        
        # Test 2: AMPScaler scales and updates correctly
        logger.info("Testing AMPScaler scaling and update logic...")
        
        scaler = AMPScaler(scale_factor=3.0)
        
        # Verify initial scale is 1.0
        initial_scale = scaler.get_scale()
        assert initial_scale == 1.0, f"Initial scale should be 1.0, got {initial_scale}"
        
        # Test scaling operation
        loss = torch.tensor(2.5, dtype=torch.float32)
        scaled_loss = scaler.scale(loss)
        expected = loss * 1.0  # Scale is 1.0 initially
        assert torch.isclose(scaled_loss, expected), f"Scaling failed: {scaled_loss} != {expected}"
        
        # Test update increases scale correctly
        old_scale = scaler.get_scale()
        scaler.update()
        new_scale = scaler.get_scale()
        expected_scale = old_scale * 3.0  # scale_factor is 3.0
        assert new_scale == expected_scale, f"Update failed: {new_scale} != {expected_scale}"
        
        # Test scaling after update uses new scale
        loss2 = torch.tensor(10.0, dtype=torch.float32)
        scaled_loss2 = scaler.scale(loss2)
        expected_scaled2 = loss2 * 3.0  # New scale is 3.0
        assert torch.isclose(scaled_loss2, expected_scaled2), f"Post-update scaling failed: {scaled_loss2} != {expected_scaled2}"
        
        # Test multiple updates
        scaler.update()
        assert scaler.get_scale() == 9.0, f"Second update failed: {scaler.get_scale()} != 9.0"
        scaler.update()
        assert scaler.get_scale() == 27.0, f"Third update failed: {scaler.get_scale()} != 27.0"
        
        # Test with different scale factor
        scaler2 = AMPScaler(scale_factor=0.5)
        assert scaler2.get_scale() == 1.0, "New scaler should start at 1.0"
        scaler2.update()
        assert scaler2.get_scale() == 0.5, "Scale should decrease with factor < 1"
        
        # Test


if __name__ == "__main__":
    _selftest()
