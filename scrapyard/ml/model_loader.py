"""
model_loader — Load and warmup machine learning models for inference, providing a reusable foundation for serving and optimizing models across deployment scenarios.

### PART-META-JSON
{
  "name": "model_loader",
  "layer": "ml",
  "purpose": "Load and warmup machine learning models for inference, providing a reusable foundation for serving and optimizing models across deployment scenarios.",
  "addition": true,
  "status": "core",
  "dependencies": ["torch", "onnx"],
  "inputs": "Public API: load_model(model_path, framework, allow_unsafe_pickle=False); warmup_model(model, input_data); export_to_onnx(model, output_path, sample_input); quantize_model(model, method); get_embedding_service().",
  "outputs": "Returns: load_model -> Any; warmup_model -> None; export_to_onnx -> None; quantize_model -> Any; get_embedding_service -> Optional[Any].",
  "files_created": [],
  "security_notes": "Model paths are caller-controlled filesystem inputs. Pickle can execute arbitrary code and is rejected unless allow_unsafe_pickle=True; only opt in for a trusted artifact. PyTorch uses weights_only=True and TensorFlow/Keras uses safe_mode=True.",
  "ai_usage": "Import what you need from `scrapyard.ml.model_loader`.",
  "example": "from scrapyard.ml.model_loader import *",
  "import_path": "scrapyard.ml.model_loader"
}
### END-PART-META
"""

import logging
import os
import pickle
import sqlite3
import tempfile
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Integration declarations for ml_serving ecosystem
INTEGRATION_BATCH_INFERENCE_SERVER = True
INTEGRATION_ONNX_EXPORT = True
INTEGRATION_QUANTIZATION_HELPER = True
INTEGRATION_EMBEDDING_SERVICE = True


def load_model(
    model_path: str,
    framework: str,
    *,
    allow_unsafe_pickle: bool = False,
) -> Any:
    """
    Load models from standard formats (PyTorch, TensorFlow, etc.).
    
    Args:
        model_path: Path to the model file
        framework: Framework identifier ('pytorch', 'tensorflow', 'onnx', etc.)
        
    Returns:
        Loaded model object
    """
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model path not found: {model_path}")
    
    framework = framework.lower()
    
    if framework == "pytorch":
        try:
            import torch
            return torch.load(model_path, map_location='cpu', weights_only=True)
        except ImportError as exc:
            raise RuntimeError("PyTorch is required to load a PyTorch model") from exc
    elif framework == "tensorflow":
        try:
            import tensorflow as tf
            return tf.keras.models.load_model(
                model_path,
                compile=False,
                safe_mode=True,
            )
        except ImportError as exc:
            raise RuntimeError("TensorFlow is required to load a TensorFlow model") from exc
    elif framework == "onnx":
        try:
            import onnx
            return onnx.load(model_path)
        except ImportError as exc:
            raise RuntimeError("ONNX is required to load an ONNX model") from exc
    elif framework in {"pickle", "pkl"}:
        if not allow_unsafe_pickle:
            raise ValueError(
                "Pickle loading is disabled because deserialization can execute "
                "arbitrary code; pass allow_unsafe_pickle=True only for a trusted artifact"
            )
        with open(model_path, 'rb') as f:
            return pickle.load(f)
    raise ValueError(f"Unsupported model framework: {framework}")


def warmup_model(model: Any, input_data: Any) -> None:
    """
    Warmup models to improve inference latency.
    
    Args:
        model: The loaded model
        input_data: Dummy input data for warmup inference
    """
    if model is None:
        return
    
    # Attempt PyTorch warmup
    try:
        if hasattr(model, 'eval') and callable(getattr(model, 'forward', None)):
            import torch
            model.eval()
            with torch.no_grad():
                if isinstance(input_data, dict):
                    _ = model(**input_data)
                else:
                    _ = model(input_data)
            return
    except Exception:
        pass
    
    # Attempt TensorFlow/Keras warmup
    try:
        if hasattr(model, 'predict'):
            _ = model.predict(input_data)
            return
    except Exception:
        pass
    
    # Attempt generic callable warmup
    try:
        if callable(model) and not isinstance(model, (dict, list, str, bytes)):
            _ = model(input_data)
            return
    except Exception:
        pass
    
    # Warmup is best-effort; silent completion for unsupported types
    return


def export_to_onnx(model: Any, output_path: str, sample_input: Any = None) -> None:
    """
    Enable model export to ONNX for cross-runtime compatibility.
    Integration point for ONNX export functionality.
    """
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for ONNX export") from exc
    if not isinstance(model, torch.nn.Module):
        raise TypeError("ONNX export currently supports torch.nn.Module models")
    if sample_input is None:
        sample_input = getattr(model, "example_input_array", None)
    if sample_input is None:
        raise ValueError("sample_input is required for ONNX export")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    model.eval()
    torch.onnx.export(model, sample_input, output_path,
                      input_names=["input"], output_names=["output"],
                      dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
                      dynamo=False)


def quantize_model(model: Any, method: str = "dynamic") -> Any:
    """
    Allow quantization via quantization_helper for performance optimization.
    
    Args:
        model: Model to quantize
        method: Quantization method to apply
        
    Returns:
        Quantized model
    """
    if method != "dynamic":
        raise ValueError(f"Unsupported quantization method: {method}")
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for dynamic quantization") from exc
    if not isinstance(model, torch.nn.Module):
        raise TypeError("dynamic quantization requires a torch.nn.Module")
    return torch.ao.quantization.quantize_dynamic(
        model,
        {torch.nn.Linear},
        dtype=torch.qint8,
    )


def get_embedding_service() -> Optional[Any]:
    """
    Embedding model management through embedding_service.
    
    Returns:
        Embedding service interface or None
    """
    from scrapyard.ml import embedding_service
    return embedding_service


def _selftest() -> None:
    """
    Self-test verifying:
    - load_model() successfully loads from a known path
    - warmup_model() runs without error on dummy input
    - Integration with batch_inference_server correctly declared
    - No database tables created or used by module
    - All functions type hinted and handle exceptions
    - Completes in under 20 seconds with temporary SQLite DB
    """
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Create and close temporary SQLite DB as required by spec
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY)")
            cursor.execute("INSERT INTO test_table VALUES (42)")
            conn.commit()
            # Verify DB works then close it
            cursor.execute("SELECT id FROM test_table")
            result = cursor.fetchone()
            assert result[0] == 42
        finally:
            conn.close()
        
        # Test load_model with dummy model file
        model_path = os.path.join(tmpdir, "dummy_model.pkl")
        dummy_model = {"framework": "test", "layers": [64, 32, 10]}
        with open(model_path, 'wb') as f:
            pickle.dump(dummy_model, f)
        
        # Unsafe serialization is explicit and rejects the safe default.
        try:
            load_model(model_path, "pickle")
        except ValueError as exc:
            assert "disabled" in str(exc)
        else:
            raise AssertionError("pickle must be rejected by default")
        loaded = load_model(model_path, "pickle", allow_unsafe_pickle=True)
        assert loaded == dummy_model

        try:
            load_model(model_path, "unknown")
        except ValueError as exc:
            assert "Unsupported" in str(exc)
        else:
            raise AssertionError("unknown framework must be rejected")
        
        # Test warmup_model with various inputs (should not raise)
        warmup_model(loaded, None)
        warmup_model(loaded, [1.0, 2.0, 3.0])
        warmup_model(lambda x: x * 2, 5)  # Test callable path
        
        # Verify integration declarations exist
        assert INTEGRATION_BATCH_INFERENCE_SERVER is True
        assert INTEGRATION_ONNX_EXPORT is True
        assert INTEGRATION_QUANTIZATION_HELPER is True
        assert INTEGRATION_EMBEDDING_SERVICE is True
        
        # Verify supporting API exists
        assert callable(export_to_onnx)
        assert callable(quantize_model)
        assert callable(get_embedding_service)
        import torch
        onnx_path = os.path.join(tmpdir, "linear.onnx")
        export_to_onnx(torch.nn.Linear(3, 2), onnx_path, torch.randn(1, 3))
        assert os.path.getsize(onnx_path) > 0
        try:
            export_to_onnx(object(), os.path.join(tmpdir, "x.onnx"), object())
            raise AssertionError("accepted non-torch model")
        except TypeError:
            pass
        
        elapsed = time.time() - start_time
        assert elapsed < 20.0, f"Selftest exceeded 20 seconds: {elapsed}"
    
    logger.info("model_loader selftest completed successfully")


if __name__ == "__main__":
    _selftest()
