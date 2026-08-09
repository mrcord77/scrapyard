"""
parameter_count_summary — ** Generates a concise summary of parameter counts in neural network models, aiding in model analysis and optimization. Designed as a reusable, lightweight tool for ML developers working within the `n

### PART-META-JSON
{
  "name": "parameter_count_summary",
  "layer": "ml",
  "purpose": "Generates a concise summary of parameter counts in neural network models, aiding in model analysis and optimization. Designed as a reusable, lightweight tool for ML developers working within the `n.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: count_parameters(model); ParameterCounter(...).",
  "outputs": "Returns: count_parameters -> Dict[str, int].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.parameter_count_summary`.",
  "example": "from scrapyard.ml.parameter_count_summary import *",
  "import_path": "scrapyard.ml.parameter_count_summary"
}
### END-PART-META
"""
import logging
from typing import Any, Dict
import json
import tempfile
import sqlite3
import os

# Module metadata for scrapyard integration
PART_META_JSON = {
    "name": "scrapyard.ml.parameter_count_summary",
    "layer": "ml"
}

logger = logging.getLogger(__name__)


class ParameterCounter:
    """Analyzes parameter counts in neural network models across frameworks."""
    
    def __init__(self, model: Any) -> None:
        self.model = model
        self._framework = self._detect_framework()
        logger.debug(f"ParameterCounter initialized with framework: {self._framework}")
    
    def _detect_framework(self) -> str:
        """Detect the ML framework of the model."""
        if self.model is None:
            return "none"
        
        # Check for PyTorch nn.Module
        try:
            import torch.nn as nn
            if isinstance(self.model, nn.Module):
                return "pytorch"
        except ImportError:
            pass
        
        # Check for TensorFlow/Keras models
        try:
            import tensorflow as tf
            if isinstance(self.model, (tf.keras.Model, tf.Module)):
                return "tensorflow"
        except ImportError:
            pass
        
        return "unknown"
    
    def summarize(self) -> Dict[str, int]:
        """
        Compute parameter counts.
        
        Returns:
            Dict with keys: 'total', 'trainable', 'non_trainable'
        """
        if self._framework == "none" or self._framework == "unknown":
            return {"total": 0, "trainable": 0, "non_trainable": 0}
        
        if self._framework == "pytorch":
            return self._count_pytorch()
        elif self._framework == "tensorflow":
            return self._count_tensorflow()
        
        return {"total": 0, "trainable": 0, "non_trainable": 0}
    
    def _count_pytorch(self) -> Dict[str, int]:
        """Count parameters for PyTorch models."""
        trainable = 0
        non_trainable = 0
        
        for param in self.model.parameters():
            num = param.numel()
            if param.requires_grad:
                trainable += num
            else:
                non_trainable += num
        
        return {
            "total": trainable + non_trainable,
            "trainable": trainable,
            "non_trainable": non_trainable
        }
    
    def _count_tensorflow(self) -> Dict[str, int]:
        """Count parameters for TensorFlow models."""
        trainable = 0
        non_trainable = 0
        
        # Handle Keras models and tf.Module
        if hasattr(self.model, 'trainable_variables'):
            for var in self.model.trainable_variables:
                trainable += var.numpy().size
        
        if hasattr(self.model, 'non_trainable_variables'):
            for var in self.model.non_trainable_variables:
                non_trainable += var.numpy().size
        
        # Fallback for edge cases where variables exist but aren't categorized
        if trainable == 0 and non_trainable == 0 and hasattr(self.model, 'variables'):
            for var in self.model.variables:
                if hasattr(var, 'trainable') and not var.trainable:
                    non_trainable += var.numpy().size
                else:
                    trainable += var.numpy().size
        
        return {
            "total": trainable + non_trainable,
            "trainable": trainable,
            "non_trainable": non_trainable
        }
    
    def to_dataframe(self) -> Any:
        """
        Convert summary to pandas DataFrame.
        
        Returns:
            pd.DataFrame with columns 'Metric' and 'Count'
        """
        import pandas as pd
        summary = self.summarize()
        data = [
            {"Metric": "total", "Count": summary["total"]},
            {"Metric": "trainable", "Count": summary["trainable"]},
            {"Metric": "non_trainable", "Count": summary["non_trainable"]}
        ]
        return pd.DataFrame(data)


def count_parameters(model: Any) -> Dict[str, int]:
    """
    Convenience function to count parameters in a model.
    
    Args:
        model: PyTorch nn.Module or TensorFlow/Keras model
        
    Returns:
        Dict with total, trainable, and non_trainable counts
    """
    counter = ParameterCounter(model)
    return counter.summarize()


def _selftest() -> None:
    """
    Offline self-test for parameter counting functionality.
    Validates PyTorch and TensorFlow integration, edge cases, and logging.
    """
    logger.info("Starting parameter_count_summary self-test")
    
    errors = []
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Validate SQLite integration (scrapyard logging compatibility check)
        db_path = os.path.join(tmpdir, "test_log.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY, msg TEXT)")
        cursor.execute("INSERT INTO logs (msg) VALUES (?)", ("selftest_start",))
        conn.commit()
        conn.close()
        
        # Test 1: None model
        try:
            result = count_parameters(None)
            assert result == {"total": 0, "trainable": 0, "non_trainable": 0}
            logger.debug("Test 1 passed: None model")
        except Exception as e:
            errors.append(f"None model: {e}")
        
        # Test 2: Invalid model type
        try:
            result = count_parameters("not_a_model")
            assert result == {"total": 0, "trainable": 0, "non_trainable": 0}
            logger.debug("Test 2 passed: Invalid type")
        except Exception as e:
            errors.append(f"Invalid type: {e}")
        
        # Test 3: PyTorch models
        try:
            import torch
            import torch.nn as nn
            
            # Simple linear model: 10*5 + 5 = 55 params
            model = nn.Linear(10, 5)
            result = count_parameters(model)
            assert result["total"] == 55, f"Expected 55, got {result['total']}"
            assert result["trainable"] == 55
            assert result["non_trainable"] == 0
            
            # Freeze and verify non_trainable count
            for param in model.parameters():
                param.requires_grad = False
            result = count_parameters(model)
            assert result["trainable"] == 0
            assert result["non_trainable"] == 55
            
            # Nested model (Sequential)
            nested = nn.Sequential(
                nn.Linear(5, 3),   # 5*3 + 3 = 18
                nn.ReLU(),
                nn.Linear(3, 1)    # 3*1 + 1 = 4
            )
            result = count_parameters(nested)
            assert result["total"] == 22, f"Nested expected 22, got {result['total']}"
            
            # Empty model
            empty = nn.Sequential()
            result = count_parameters(empty)
            assert result["total"] == 0
            
            # Test DataFrame output
            counter = ParameterCounter(nested)
            df = counter.to_dataframe()
            assert len(df) == 3
            assert df["Count"].sum() == 22 + 22  # total appears once, but we check structure
            
            logger.debug("Test 3 passed: PyTorch")
        except ImportError:
            logger.info("PyTorch not available, skipping PyTorch tests")
        except Exception as e:
            errors.append(f"PyTorch: {e}")
        
        # Test 4: TensorFlow models
        try:
            import tensorflow as tf
            
            # Simple sequential model
            model = tf.keras.Sequential([
                tf.keras.layers.Dense(5, input_shape=(10,), use_bias=True),  # 55
                tf.keras.layers.Dense(1, use_bias=True)                       # 6
            ])
            
            result = count_parameters(model)
            assert result["total"] == 61, f"TF expected 61, got {result['total']}"
            assert result["trainable"] == 61
            assert result["non_trainable"] == 0
            
            # Freeze first layer
            model.layers[0].trainable = False
            result = count_parameters(model)
            assert result["trainable"] == 6
            assert result["non_trainable"] == 55
            
            # Nested functional API
            inputs = tf.keras.Input(shape=(4,))
            x = tf.keras.layers.Dense(3)(inputs)    # 4*3 + 3 = 15
            outputs = tf.keras.layers.Dense(2)(x)   # 3*2 + 2 = 8
            nested = tf.keras.Model(inputs=inputs, outputs=outputs)
            
            result = count_parameters(nested)
            assert result["total"] == 23, f"TF nested expected 23, got {result['total']}"
            
            # Empty model
            empty = tf.keras.Sequential()
            result = count_parameters(empty)
            assert result["total"] == 0
            
            logger.debug("Test 4 passed: TensorFlow")
        except ImportError:
            logger.info("TensorFlow not available, skipping TensorFlow tests")
        except Exception as e:
            errors.append(f"TensorFlow: {e}")
        
        # Test 5: JSON serialization of results
        try:
            import torch.nn as nn
            model = nn.Linear(2, 2)  # 6 params
            result = count_parameters(model)
            json_str = json.dumps(result)
            parsed = json.loads(json_str)
            assert parsed["total"] == 6
            logger.debug("Test 5 passed: JSON serialization")
        except Exception as e:
            errors.append(f"JSON: {e}")
    
    if errors:
        msg = "Self-test failures:\n" + "\n".join(errors)
        logger.error(msg)
        raise AssertionError(msg)
    
    logger.info("Self-test completed successfully")


if __name__ == "__main__":
    _selftest()
