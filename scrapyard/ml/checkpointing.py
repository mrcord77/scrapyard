"""
checkpointing — Save/load torch training checkpoints (model + optimizer + metadata) with best-metric tracking, latest/best symmetry, and retention pruning.

### PART-META-JSON
{
  "name": "checkpointing",
  "layer": "ml",
  "purpose": "Checkpoint management for training loops: CheckpointManager.save() persists model/optimizer state_dicts with epoch, metric, and user metadata; load()/load_latest()/load_best() restore them into live modules; keep_last retention prunes old checkpoint files automatically; best-metric tracking (min or max mode) marks and preserves the best checkpoint.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "torch"
  ],
  "inputs": "CheckpointManager(dir, keep_last=3, metric_mode='min'); save(model, optimizer, epoch, metric, metadata); load_latest(model, optimizer); load_best(model, optimizer).",
  "outputs": "checkpoint files 'ckpt_epoch<N>.pt' plus 'best.pt'; load returns {'epoch', 'metric', 'metadata'} after restoring states in place.",
  "files_created": [
    "<dir>/ckpt_epoch<N>.pt",
    "<dir>/best.pt"
  ],
  "security_notes": "Checkpoints are torch.save pickles: loading executes the pickle machinery, so ONLY load checkpoints you produced or trust - a malicious .pt file is arbitrary code execution. load() uses weights_only=True by default (torch's hardened loader) and only falls back to full pickle when metadata requires it and allow_full_pickle=True is passed explicitly. Checkpoints contain full model weights; protect the directory accordingly.",
  "ai_usage": "mgr = CheckpointManager(dir); mgr.save(model, opt, epoch=e, metric=val_loss); mgr.load_best(model, opt) before eval.",
  "example": "from scrapyard.ml.checkpointing import CheckpointManager",
  "import_path": "scrapyard.ml.checkpointing"
}
### END-PART-META
"""
import os
import glob
import logging
import re
import shutil
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_EPOCH_RE = re.compile(r"ckpt_epoch(\d+)\.pt$")


class CheckpointManager:
    """Manages torch checkpoints in a directory with retention and best tracking."""

    def __init__(self, directory: str, keep_last: int = 3,
                 metric_mode: str = "min"):
        if metric_mode not in ("min", "max"):
            raise ValueError("metric_mode must be 'min' or 'max'")
        if keep_last < 1:
            raise ValueError("keep_last must be >= 1")
        self.directory = os.path.abspath(directory)
        os.makedirs(self.directory, exist_ok=True)
        self.keep_last = keep_last
        self.metric_mode = metric_mode
        self.best_metric: Optional[float] = None

    # -- paths ---------------------------------------------------------------
    def _path(self, epoch: int) -> str:
        return os.path.join(self.directory, f"ckpt_epoch{epoch}.pt")

    @property
    def best_path(self) -> str:
        return os.path.join(self.directory, "best.pt")

    def list_checkpoints(self) -> list:
        """Epoch-sorted list of (epoch, path) for retained checkpoints."""
        out = []
        for p in glob.glob(os.path.join(self.directory, "ckpt_epoch*.pt")):
            m = _EPOCH_RE.search(os.path.basename(p))
            if m:
                out.append((int(m.group(1)), p))
        return sorted(out)

    # -- save ----------------------------------------------------------------
    def save(self, model, optimizer=None, *, epoch: int, metric: Optional[float] = None,
             metadata: Optional[Dict[str, Any]] = None) -> str:
        """Persist a checkpoint; prunes old ones and updates best.pt."""
        import torch
        payload = {
            "epoch": int(epoch),
            "metric": None if metric is None else float(metric),
            "metadata": dict(metadata or {}),
            "model_state": model.state_dict(),
            "optimizer_state": optimizer.state_dict() if optimizer is not None else None,
        }
        path = self._path(epoch)
        torch.save(payload, path)
        logger.info("Saved checkpoint %s", path)

        # best tracking
        if metric is not None:
            better = (self.best_metric is None
                      or (self.metric_mode == "min" and metric < self.best_metric)
                      or (self.metric_mode == "max" and metric > self.best_metric))
            if better:
                self.best_metric = float(metric)
                shutil.copyfile(path, self.best_path)
                logger.info("New best checkpoint (metric=%s)", metric)

        # retention pruning (never touches best.pt)
        ckpts = self.list_checkpoints()
        while len(ckpts) > self.keep_last:
            old_epoch, old_path = ckpts.pop(0)
            try:
                os.remove(old_path)
                logger.debug("Pruned checkpoint epoch %s", old_epoch)
            except OSError as e:  # pragma: no cover - fs race
                logger.warning("Could not prune %s: %s", old_path, e)
        return path

    # -- load ----------------------------------------------------------------
    def _load_payload(self, path: str, allow_full_pickle: bool = False) -> Dict[str, Any]:
        import torch
        try:
            return torch.load(path, weights_only=True)
        except Exception:
            if not allow_full_pickle:
                raise
            return torch.load(path, weights_only=False)

    def load(self, path: str, model, optimizer=None,
             allow_full_pickle: bool = False) -> Dict[str, Any]:
        """Restore model (and optimizer) state from a checkpoint file."""
        payload = self._load_payload(path, allow_full_pickle)
        model.load_state_dict(payload["model_state"])
        if optimizer is not None and payload.get("optimizer_state") is not None:
            optimizer.load_state_dict(payload["optimizer_state"])
        return {"epoch": payload.get("epoch"), "metric": payload.get("metric"),
                "metadata": payload.get("metadata", {})}

    def load_latest(self, model, optimizer=None,
                    allow_full_pickle: bool = False) -> Optional[Dict[str, Any]]:
        ckpts = self.list_checkpoints()
        if not ckpts:
            return None
        return self.load(ckpts[-1][1], model, optimizer, allow_full_pickle)

    def load_best(self, model, optimizer=None,
                  allow_full_pickle: bool = False) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.best_path):
            return None
        return self.load(self.best_path, model, optimizer, allow_full_pickle)


def _selftest():
    import tempfile
    import torch
    import torch.nn as nn

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        torch.manual_seed(0)
        model = nn.Linear(4, 2)
        opt = torch.optim.SGD(model.parameters(), lr=0.1)
        mgr = CheckpointManager(tmpdir, keep_last=2, metric_mode="min")

        # save epochs with improving-then-worsening metric
        mgr.save(model, opt, epoch=1, metric=1.0, metadata={"note": "e1"})
        w_at_best = model.weight.detach().clone()
        mgr.save(model, opt, epoch=2, metric=0.5)  # best
        w_best = model.weight.detach().clone()
        with torch.no_grad():
            model.weight += 1.0  # change weights
        mgr.save(model, opt, epoch=3, metric=0.9)  # worse

        # retention pruned epoch 1, kept 2 and 3, best.pt intact
        epochs = [e for e, _ in mgr.list_checkpoints()]
        assert epochs == [2, 3], epochs
        assert os.path.exists(mgr.best_path)
        assert mgr.best_metric == 0.5

        # load_latest restores epoch-3 weights (the shifted ones)
        w_shifted = model.weight.detach().clone()
        with torch.no_grad():
            model.weight.zero_()
        info = mgr.load_latest(model, opt)
        assert info["epoch"] == 3 and info["metric"] == 0.9
        assert torch.allclose(model.weight, w_shifted)

        # load_best restores the epoch-2 weights
        info_b = mgr.load_best(model, opt)
        assert info_b["epoch"] == 2 and info_b["metric"] == 0.5
        assert torch.allclose(model.weight, w_best)
        assert not torch.allclose(w_best, w_shifted)

        # metadata round-trips
        info1 = mgr.load(mgr.best_path, model)
        assert isinstance(info1["metadata"], dict)

        # empty dir returns None instead of exploding
        empty = CheckpointManager(os.path.join(tmpdir, "empty"))
        assert empty.load_latest(model) is None
        assert empty.load_best(model) is None

        # config validation
        try:
            CheckpointManager(tmpdir, metric_mode="sideways")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
        try:
            CheckpointManager(tmpdir, keep_last=0)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    print("checkpointing selftest passed")


if __name__ == "__main__":
    _selftest()
