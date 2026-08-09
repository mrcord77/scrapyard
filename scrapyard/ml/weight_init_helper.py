"""
weight_init_helper — ** The `scrapyard.ml.weight_init_helper` module provides flexible and reusable utilities for initializing weights in neural network layers, supporting common strategies like Xavier and Kaiming initial

### PART-META-JSON
{
  "name": "weight_init_helper",
  "layer": "ml",
  "purpose": "Provides flexible and reusable utilities for initializing weights in neural network layers, supporting common strategies like Xavier and Kaiming initial.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: xavier_uniform_init(tensor); kaiming_normal_init(tensor, fan); WeightInitializer(...).",
  "outputs": "Returns: xavier_uniform_init -> torch.Tensor; kaiming_normal_init -> torch.Tensor.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.weight_init_helper`.",
  "example": "from scrapyard.ml.weight_init_helper import *",
  "import_path": "scrapyard.ml.weight_init_helper"
}
### END-PART-META
"""
import torch
import torch.nn as nn
import math
import logging
import tempfile
import sqlite3

logger = logging.getLogger(__name__)


class WeightInitializer:
    def __init__(self, strategy: str = "xavier_uniform"):
        self.strategy = strategy.lower()
    
    def apply(self, module: nn.Module):
        if hasattr(module, 'weight') and module.weight is not None:
            tensor = module.weight.data
            if self.strategy == "xavier_uniform":
                self.xavier_uniform_init(tensor)
            elif self.strategy == "kaiming_normal":
                fan_in = self._calculate_fan_in(module)
                self.kaiming_normal_init(tensor, fan_in)
            else:
                raise ValueError(f"Unknown initialization strategy: {self.strategy}")
    
    def _calculate_fan_in(self, module: nn.Module) -> int:
        """Calculate fan_in for a module."""
        if hasattr(module, 'in_features'):
            return module.in_features
        elif hasattr(module, 'weight'):
            shape = module.weight.shape
            if len(shape) >= 2:
                fan = shape[1]
                for s in shape[2:]:
                    fan *= s
                return fan
        return 1

    def xavier_uniform_init(self, tensor: torch.Tensor) -> torch.Tensor:
        return torch.nn.init.xavier_uniform_(tensor)

    def kaiming_normal_init(self, tensor: torch.Tensor, fan: int) -> torch.Tensor:
        std = math.sqrt(2.0 / fan)
        with torch.no_grad():
            return tensor.normal_(0, std)


def xavier_uniform_init(tensor: torch.Tensor) -> torch.Tensor:
    return torch.nn.init.xavier_uniform_(tensor)


def kaiming_normal_init(tensor: torch.Tensor, fan: int) -> torch.Tensor:
    std = math.sqrt(2.0 / fan)
    with torch.no_grad():
        return tensor.normal_(0, std)


def _selftest():
    """Module-level selftest validating weight initialization strategies."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = f"{tmpdir}/test_results.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS results (test_name TEXT PRIMARY KEY, passed INTEGER)")
        
        tests_run = 0
        tests_passed = 0
        
        try:
            # Test 1: WeightInitializer with xavier_uniform on Linear layer
            tests_run += 1
            linear = nn.Linear(10, 5, bias=False)
            linear.weight.data.fill_(0.0)
            initializer = WeightInitializer(strategy="xavier_uniform")
            initializer.apply(linear)
            assert linear.weight.data.abs().max() > 0, "Xavier uniform should initialize non-zero weights"
            limit = math.sqrt(6.0 / (10 + 5))
            assert linear.weight.data.abs().max() <= limit, "Xavier weights exceed uniform bounds"
            cursor.execute("INSERT OR REPLACE INTO results VALUES (?, 1)", ("xavier_uniform_init",))
            tests_passed += 1
            
            # Test 2: WeightInitializer with kaiming_normal on Linear layer
            tests_run += 1
            linear2 = nn.Linear(20, 10, bias=False)
            linear2.weight.data.fill_(0.0)
            initializer2 = WeightInitializer(strategy="kaiming_normal")
            initializer2.apply(linear2)
            assert linear2.weight.data.abs().max() > 0, "Kaiming normal should initialize non-zero weights"
            expected_std = math.sqrt(2.0 / 20)
            actual_std = linear2.weight.data.std().item()
            assert 0.5 * expected_std < actual_std < 2.0 * expected_std, "Kaiming std dev out of expected range"
            cursor.execute("INSERT OR REPLACE INTO results VALUES (?, 1)", ("kaiming_normal_init",))
            tests_passed += 1
            
            # Test 3: Standalone xavier_uniform_init function
            tests_run += 1
            tensor = torch.zeros(3, 4)
            result = xavier_uniform_init(tensor)
            assert result is tensor, "xavier_uniform_init should return input tensor"
            assert tensor.abs().max() > 0, "Standalone Xavier should modify tensor"
            cursor.execute("INSERT OR REPLACE INTO results VALUES (?, 1)", ("xavier_function",))
            tests_passed += 1
            
            # Test 4: Standalone kaiming_normal_init function with explicit fan
            tests_run += 1
            tensor2 = torch.zeros(5, 10)
            fan_val = 10
            kaiming_normal_init(tensor2, fan_val)
            assert tensor2.abs().max() > 0, "Standalone Kaiming should modify tensor"
            expected_std = math.sqrt(2.0 / fan_val)
            actual_std = tensor2.std().item()
            assert 0.5 * expected_std < actual_std < 2.0 * expected_std, "Standalone Kaiming std dev mismatch"
            cursor.execute("INSERT OR REPLACE INTO results VALUES (?, 1)", ("kaiming_function",))
            tests_passed += 1
            
            # Test 5: Unknown strategy raises ValueError
            tests_run += 1
            try:
                bad_initializer = WeightInitializer(strategy="unknown_strategy")
                bad_layer = nn.Linear(2, 2)
                bad_initializer.apply(bad_layer)
                raise AssertionError("Should have raised ValueError for unknown strategy")
            except ValueError as e:
                assert "unknown" in str(e).lower() or "strategy" in str(e).lower()
                cursor.execute("INSERT OR REPLACE INTO results VALUES (?, 1)", ("error_handling",))
                tests_passed += 1
            
            # Test 6: Type hints validation - functions accept correct types
            tests_run += 1
            test_tensor = torch.empty(2, 3)
            xavier_uniform_init(test_tensor)
            kaiming_normal_init(test_tensor, 3)
            cursor.execute("INSERT OR REPLACE INTO results VALUES (?, 1)", ("type_validation",))
            tests_passed += 1
            
            conn.commit()
            
        finally:
            conn.close()
        
        if tests_passed != tests_run:
            raise AssertionError(f"Self-test failed: {tests_passed}/{tests_run} tests passed")
        
        logger.info(f"scrapyard.ml.weight_init_helper self-test passed: {tests_passed}/{tests_run}")


if __name__ == "__main__":
    _selftest()
