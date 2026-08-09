"""
quantization_helper — Apply quantization techniques to reduce inference time and memory usage: real symmetric linear quantization for tensors/parameter dicts and real torch dynamic/static (weight fake-quant) quantization for nn.Modules.

### PART-META-JSON
{
  "name": "quantization_helper",
  "layer": "ml",
  "purpose": "Working quantization utilities: quantize_tensor()/dequantize_tensor() implement symmetric linear int quantization at any bit width with stored scale; quantize_model() applies torch.ao.quantization.quantize_dynamic to nn.Modules (dynamic config) or weight-only fake-quantization at config.bits (static config), and quantizes dict-of-arrays models into QuantizedTensor structures; dequantize_model() reconstructs float values from quantized structures.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "torch"
  ],
  "inputs": "QuantConfig(quantization_type='static'|'dynamic', bits=8, axes=None); quantize_model(nn.Module | {name: values}, config); quantize_tensor(list, bits).",
  "outputs": "Dynamic-quantized torch module, fake-quantized module copy, or {name: QuantizedTensor(data, scale, bits)}; dequantize returns float lists with error bounded by scale/2 per element.",
  "files_created": [],
  "security_notes": "Pure numerical transformation, no I/O or network. Quantization is lossy by design - dequantize_model() recovers values only to within scale/2 per element, and torch-module quantization cannot be reversed (dequantize raises TypeError for modules instead of pretending). Unsupported model types raise TypeError rather than silently returning the input unchanged (the previous behavior).",
  "ai_usage": "q = quantize_model({'w': weights}, QuantConfig('static', 8)); back = dequantize_model(q, QuantConfig('static', 8)).",
  "example": "from scrapyard.ml.quantization_helper import quantize_model, QuantConfig",
  "import_path": "scrapyard.ml.quantization_helper"
}
### END-PART-META
"""
import logging
from typing import Optional, List, Any, Dict

from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class QuantConfig:
    quantization_type: str  # 'static' or 'dynamic'
    bits: int = 8  # Number of bits for quantization
    axes: Optional[List[str]] = None  # Parameter names to quantize (None = all)


@dataclass
class QuantizedTensor:
    """Symmetric linear quantization: value ~= data * scale."""
    data: List[int]
    scale: float
    bits: int


def quantize_tensor(values: List[float], bits: int = 8) -> QuantizedTensor:
    """Symmetric linear quantization of a float sequence to `bits`-bit ints."""
    if bits < 2 or bits > 32:
        raise ValueError("bits must be in [2, 32]")
    vals = [float(v) for v in values]
    qmax = (1 << (bits - 1)) - 1
    max_abs = max((abs(v) for v in vals), default=0.0)
    scale = (max_abs / qmax) if max_abs > 0 else 1.0
    data = [max(-qmax - 1, min(qmax, round(v / scale))) for v in vals]
    return QuantizedTensor(data=data, scale=scale, bits=bits)


def dequantize_tensor(qt: QuantizedTensor) -> List[float]:
    return [d * qt.scale for d in qt.data]


def _validate_config(config: QuantConfig) -> None:
    if config.quantization_type not in ("static", "dynamic"):
        raise ValueError(f"Unsupported quantization type: {config.quantization_type}")


def _is_torch_module(model: Any) -> bool:
    try:
        import torch.nn as nn
        return isinstance(model, nn.Module)
    except ImportError:  # pragma: no cover - torch is an env requirement
        return False


def quantize_model(model: Any, config: QuantConfig) -> Any:
    """Quantizes the given model according to the provided configuration.

    - torch nn.Module + 'dynamic': torch.ao.quantization.quantize_dynamic on
      Linear layers (real int8 dynamic quantization).
    - torch nn.Module + 'static': weight-only fake quantization — every float
      parameter is quantized to config.bits and dequantized back in a deep copy
      (simulates deployment precision loss without a calibration pass).
    - dict of {name: sequence-of-floats}: each entry (or only config.axes
      entries) becomes a QuantizedTensor.
    """
    _validate_config(config)

    if _is_torch_module(model):
        import copy
        import torch
        import torch.nn as nn
        if config.quantization_type == "dynamic":
            return torch.ao.quantization.quantize_dynamic(
                model, {nn.Linear}, dtype=torch.qint8)
        # static: weight-only fake quantization at config.bits
        qmodel = copy.deepcopy(model)
        with torch.no_grad():
            for name, param in qmodel.named_parameters():
                if config.axes is not None and name not in config.axes:
                    continue
                flat = param.detach().reshape(-1).tolist()
                qt = quantize_tensor(flat, bits=config.bits)
                restored = torch.tensor(dequantize_tensor(qt),
                                        dtype=param.dtype).reshape(param.shape)
                param.copy_(restored)
        return qmodel

    if isinstance(model, dict):
        out: Dict[str, QuantizedTensor] = {}
        for name, values in model.items():
            if config.axes is not None and name not in config.axes:
                continue
            out[name] = quantize_tensor(list(values), bits=config.bits)
        return out

    raise TypeError(
        f"Cannot quantize object of type {type(model).__name__}: expected a "
        "torch nn.Module or a dict of float sequences")


def dequantize_model(model: Any, config: QuantConfig) -> Any:
    """Dequantizes quantized structures produced by quantize_model.

    QuantizedTensor dicts/instances are reconstructed to float lists.
    torch modules raise TypeError: module quantization is lossy/in-place and
    cannot be reversed (use the original module you kept)."""
    _validate_config(config)

    if isinstance(model, QuantizedTensor):
        return dequantize_tensor(model)
    if isinstance(model, dict) and all(
            isinstance(v, QuantizedTensor) for v in model.values()):
        return {name: dequantize_tensor(qt) for name, qt in model.items()}
    if _is_torch_module(model):
        raise TypeError("torch module quantization is not reversible; keep the "
                        "original float module for full precision")
    raise TypeError(
        f"Cannot dequantize object of type {type(model).__name__}")


def _selftest() -> bool:
    """Offline self-test with real numerical checks."""
    import torch
    import torch.nn as nn

    # 1. Tensor round-trip: error bounded by scale/2 per element
    vals = [0.5, -1.25, 3.75, 0.0, -3.9]
    qt = quantize_tensor(vals, bits=8)
    back = dequantize_tensor(qt)
    assert all(abs(a - b) <= qt.scale / 2 + 1e-12 for a, b in zip(vals, back)), \
        (vals, back, qt.scale)
    # more bits -> finer scale -> smaller error
    qt16 = quantize_tensor(vals, bits=16)
    assert qt16.scale < qt.scale
    # int range respected
    qmax = (1 << 7) - 1
    assert all(-qmax - 1 <= d <= qmax for d in qt.data)
    # degenerate all-zero input survives
    z = quantize_tensor([0.0, 0.0], bits=8)
    assert dequantize_tensor(z) == [0.0, 0.0]
    try:
        quantize_tensor([1.0], bits=1)
        raise AssertionError("expected ValueError for bits=1")
    except ValueError:
        pass

    # 2. Dict model quantization (static), including axes filtering
    weights = {"w1": [0.1, -0.2, 0.3], "w2": [10.0, -20.0]}
    q = quantize_model(weights, QuantConfig("static", bits=8))
    assert set(q) == {"w1", "w2"} and isinstance(q["w1"], QuantizedTensor)
    deq = dequantize_model(q, QuantConfig("static", bits=8))
    for name in weights:
        for a, b in zip(weights[name], deq[name]):
            assert abs(a - b) <= q[name].scale / 2 + 1e-12
    q_only = quantize_model(weights, QuantConfig("static", bits=8, axes=["w1"]))
    assert set(q_only) == {"w1"}

    # 3. torch dynamic quantization actually swaps Linear for quantized Linear
    torch.manual_seed(0)
    m = nn.Sequential(nn.Linear(8, 4), nn.ReLU(), nn.Linear(4, 2))
    dq = quantize_model(m, QuantConfig("dynamic"))
    assert type(dq[0]).__module__.startswith("torch.ao.nn.quantized"), type(dq[0])
    x = torch.randn(3, 8)
    with torch.no_grad():
        y_ref = m(x)
        y_q = dq(x)
    assert y_q.shape == y_ref.shape
    assert torch.allclose(y_ref, y_q, atol=0.2), "quantized output should stay close"

    # 4. torch static (weight fake-quant): weights change slightly, model runs
    sq = quantize_model(m, QuantConfig("static", bits=6))
    with torch.no_grad():
        w_orig = m[0].weight
        w_q = sq[0].weight
        assert not torch.equal(w_orig, w_q), "fake-quant must actually change weights"
        assert torch.allclose(w_orig, w_q, atol=float(w_orig.abs().max()) / 10)
        assert sq(x).shape == y_ref.shape

    # 5. Errors are honest
    try:
        quantize_model("MockModel", QuantConfig("static", bits=8))
        raise AssertionError("expected TypeError for unsupported model type")
    except TypeError:
        pass
    try:
        quantize_model(weights, QuantConfig("banana"))
        raise AssertionError("expected ValueError for bad type")
    except ValueError:
        pass
    try:
        dequantize_model(m, QuantConfig("static"))
        raise AssertionError("expected TypeError for module dequantization")
    except TypeError:
        pass

    logger.info("Self-test completed successfully.")
    print("quantization_helper selftest passed")
    return True


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(1 if _selftest() is False else 0)
