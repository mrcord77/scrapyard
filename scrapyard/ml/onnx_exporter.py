"""
onnx_exporter — Standardized interface for exporting torch models to real ONNX format via torch.onnx.export, with metadata sidecars and output validation.

### PART-META-JSON
{
  "name": "onnx_exporter",
  "layer": "ml",
  "purpose": "Real ONNX export: export_to_onnx(model, path, input_example) runs torch.onnx.export on an nn.Module with the provided example input (tensor, or list/tuple converted to a float tensor), writes a genuine .onnx protobuf, verifies it with onnx.checker when the onnx package is available, and writes a JSON metadata sidecar (input/output shapes, opset). Non-torch models raise TypeError instead of writing a fake file.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "torch",
    "onnx"
  ],
  "inputs": "export_to_onnx(nn.Module, 'model.onnx', input_example, opset_version=17, validate=True); ModelMetadata(model_type, input_shape, output_shape).",
  "outputs": "A valid .onnx file at export_path plus '<export_path>.meta.json' sidecar with shapes/opset; raises on unsupported models or failed export.",
  "files_created": [
    "<export_path> (.onnx protobuf)",
    "<export_path>.meta.json"
  ],
  "security_notes": "Loading ONNX files executes no code, but exported graphs embed the model's learned weights - treat the .onnx artifact with the same confidentiality as the checkpoint. Export paths are used as given; validate caller-supplied paths if they originate from user input to avoid writing outside intended directories. No network access.",
  "ai_usage": "export_to_onnx(model, out_path, torch.randn(1, 8)); deploy out_path to any ONNX runtime.",
  "example": "from scrapyard.ml.onnx_exporter import export_to_onnx",
  "import_path": "scrapyard.ml.onnx_exporter"
}
### END-PART-META
"""
import os
import json
import logging
import tempfile
from typing import Any

from dataclasses import dataclass

# Setup logger
logger = logging.getLogger(__name__)


@dataclass
class ModelMetadata:
    model_type: str
    input_shape: tuple
    output_shape: tuple


def _to_example_tensor(input_example: Any):
    """Normalize the example input to a torch tensor."""
    import torch
    if isinstance(input_example, torch.Tensor):
        return input_example
    if isinstance(input_example, (list, tuple)):
        return torch.tensor(input_example, dtype=torch.float32)
    if isinstance(input_example, dict) and len(input_example) == 1:
        # single named input: {'input': [...]}
        return _to_example_tensor(next(iter(input_example.values())))
    raise TypeError("input_example must be a torch.Tensor, a (nested) list/tuple "
                    "of numbers, or a single-entry dict of one")


def export_to_onnx(model: Any, export_path: str, input_example: Any,
                   *, opset_version: int = 17, validate: bool = True) -> ModelMetadata:
    """
    Export a torch model to real ONNX format.

    :param model: torch.nn.Module to export.
    :param export_path: Path where the ONNX file will be saved.
    :param input_example: Example input (tensor / nested list / 1-entry dict).
    :param opset_version: ONNX opset to target.
    :param validate: run onnx.checker on the produced file when onnx is present.
    :return: ModelMetadata describing the exported graph.
    """
    import torch
    import torch.nn as nn

    if not isinstance(model, nn.Module):
        raise TypeError(f"Cannot export object of type {type(model).__name__}: "
                        "expected a torch.nn.Module")

    example = _to_example_tensor(input_example)
    model = model.eval()
    with torch.no_grad():
        output = model(example)

    torch.onnx.export(
        model, (example,), export_path,
        input_names=["input"], output_names=["output"],
        opset_version=opset_version, dynamo=False)

    if validate:
        try:
            import onnx
            onnx.checker.check_model(onnx.load(export_path))
        except ImportError:  # pragma: no cover - onnx is expected in this env
            logger.warning("onnx package unavailable; skipping model validation")

    meta = ModelMetadata(
        model_type=type(model).__name__,
        input_shape=tuple(example.shape),
        output_shape=tuple(output.shape),
    )
    with open(export_path + ".meta.json", "w", encoding="utf-8") as f:
        json.dump({"model_type": meta.model_type,
                   "input_shape": list(meta.input_shape),
                   "output_shape": list(meta.output_shape),
                   "opset_version": opset_version}, f)

    logger.info("Model exported to %s", export_path)
    return meta


def _selftest() -> None:
    import torch
    import torch.nn as nn

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        torch.manual_seed(0)
        model = nn.Sequential(nn.Linear(3, 8), nn.ReLU(), nn.Linear(8, 2))
        export_path = os.path.join(tmpdir, "model.onnx")

        meta = export_to_onnx(model, export_path, [[1.0, 2.0, 3.0]])
        assert os.path.exists(export_path) and os.path.getsize(export_path) > 0
        assert meta.input_shape == (1, 3) and meta.output_shape == (1, 2)

        # the file is REAL onnx protobuf, loadable and checkable
        import onnx
        loaded = onnx.load(export_path)
        onnx.checker.check_model(loaded)
        graph_inputs = [i.name for i in loaded.graph.input]
        assert "input" in graph_inputs

        # metadata sidecar written and accurate
        with open(export_path + ".meta.json", encoding="utf-8") as f:
            side = json.load(f)
        assert side["input_shape"] == [1, 3] and side["output_shape"] == [1, 2]

        # dict-form example input accepted
        p2 = os.path.join(tmpdir, "model2.onnx")
        export_to_onnx(model, p2, {"input": [[0.5, 0.5, 0.5]]})
        assert os.path.getsize(p2) > 0

        # non-torch models are refused, not faked (regression: a JSON file was
        # written and labeled .onnx)
        try:
            export_to_onnx("dummy_model", os.path.join(tmpdir, "x.onnx"),
                           {"input": [1, 2, 3]})
            raise AssertionError("expected TypeError for non-torch model")
        except TypeError:
            pass

        # bad example input rejected
        try:
            export_to_onnx(model, os.path.join(tmpdir, "y.onnx"), object())
            raise AssertionError("expected TypeError for bad input example")
        except TypeError:
            pass

    logger.info("onnx_exporter selftest passed")
    print("onnx_exporter selftest passed")


if __name__ == "__main__":
    _selftest()
