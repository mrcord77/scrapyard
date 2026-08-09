"""Positional encoding utilities for sequence models.

Implements sine/cosine-based positional encoding (original transformer style)
as well as learned positional embeddings.  The layer can be dropped into a
PyTorch ``nn.Module`` stack and supports variable sequence lengths up to
``max_len`` along with a configurable scaling factor.

### PART-META-JSON
{
  "name": "positional_encoding",
  "layer": "ml",
  "purpose": "Transformer positional encoding as a drop-in PyTorch nn.Module: fixed sinusoidal encodings (registered buffer, excluded from gradient updates) or learned embeddings (nn.Parameter, trainable), supporting 2D/3D inputs, variable sequence lengths up to max_len, odd d_model, and a configurable scaling factor.",
  "status": "core",
  "dependencies": [
    "torch"
  ],
  "inputs": "PositionalEncoding(d_model, max_len=512, scaling=1.0, learnable=False); forward(x) with x of shape (batch, seq, d_model) or (seq, d_model); get_positional_embeddings(seq_len).",
  "outputs": "Input tensor with positional encodings added (same shape/dtype/device); raw (seq_len, d_model) embedding tensors.",
  "files_created": [],
  "security_notes": "Pure in-process tensor math; no network, file, subprocess, or secret handling. Sequence lengths beyond max_len and non-2D/3D inputs raise ValueError instead of silently truncating. Learned embeddings are model weights - treat checkpoints containing them like any other model artifact (loading untrusted torch checkpoints is the risky operation, and that happens outside this module).",
  "ai_usage": "pe = PositionalEncoding(d_model=512, max_len=2048); x = pe(token_embeddings) inside your transformer block.",
  "example": "from scrapyard.ml.positional_encoding import PositionalEncoding",
  "import_path": "scrapyard.ml.positional_encoding"
}
### END-PART-META
"""

import logging
import math
import tempfile

import torch
from torch import nn

logger = logging.getLogger(__name__)

Tensor = torch.Tensor


class PositionalEncoding(nn.Module):
    """Positional encoding layer for transformer-style sequence models.

    Parameters
    ----------
    d_model:
        Dimensionality of the model embedding space.
    max_len:
        Maximum supported sequence length.
    scaling:
        Multiplicative scale applied to the positional encodings.
    learnable:
        If ``True``, the positional embeddings are learned parameters;
        otherwise fixed sinusoidal encodings are used.
    """

    def __init__(
        self,
        d_model: int,
        max_len: int = 512,
        scaling: float = 1.0,
        learnable: bool = False,
    ) -> None:
        super().__init__()
        self.d_model = d_model
        self.max_len = max_len
        self.scaling = scaling
        self.learnable = learnable

        if learnable:
            self.positional_embeddings = nn.Parameter(torch.empty(max_len, d_model))
            nn.init.normal_(self.positional_embeddings, std=0.02)
        else:
            pe = torch.zeros(max_len, d_model)
            position = torch.arange(max_len, dtype=torch.float).unsqueeze(1)
            half_dim = (d_model + 1) // 2
            div_term = torch.exp(
                torch.arange(half_dim, dtype=torch.float)
                * (-math.log(10000.0) / d_model)
            )
            angles = position * div_term
            pe[:, 0::2] = torch.sin(angles)[:, : pe[:, 0::2].shape[1]]
            pe[:, 1::2] = torch.cos(angles)[:, : pe[:, 1::2].shape[1]]
            self.register_buffer("pe", pe)

    def forward(self, x: Tensor) -> Tensor:
        """Add positional encoding to ``x``.

        Parameters
        ----------
        x:
            Input tensor of shape ``(batch_size, seq_len, d_model)`` or
            ``(seq_len, d_model)``.

        Returns
        -------
        Tensor:
            ``x`` with positional encodings added, same shape and dtype as input.
        """
        if x.ndim == 2:
            seq_len = x.size(0)
        elif x.ndim == 3:
            seq_len = x.size(1)
        else:
            raise ValueError(f"Expected 2D or 3D input, got {x.ndim}D tensor.")

        if seq_len > self.max_len:
            raise ValueError(
                f"Sequence length {seq_len} exceeds maximum length {self.max_len}."
            )

        pos = self.get_positional_embeddings(seq_len).to(
            dtype=x.dtype, device=x.device
        )
        return x + pos

    def get_positional_embeddings(self, seq_len: int) -> Tensor:
        """Return the raw positional embeddings for a sequence length.

        Parameters
        ----------
        seq_len:
            Length of the sequence.

        Returns
        -------
        Tensor:
            Positional embeddings of shape ``(seq_len, d_model)``.
        """
        if seq_len > self.max_len:
            raise ValueError(
                f"Sequence length {seq_len} exceeds maximum length {self.max_len}."
            )

        if self.learnable:
            return self.positional_embeddings[:seq_len] * self.scaling
        return self.pe[:seq_len] * self.scaling


def _selftest() -> None:
    """Offline self-test for the positional encoding module."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True):
        d_model = 64
        max_len = 20

        # Non-learnable positional encoding
        pe = PositionalEncoding(
            d_model=d_model, max_len=max_len, scaling=1.0, learnable=False
        )
        x = torch.randn(3, 10, d_model, requires_grad=True)
        out = pe(x)
        assert out.shape == (3, 10, d_model), "Non-learnable output shape is wrong."
        assert out.dtype == x.dtype, "Non-learnable output dtype changed."

        # Learned positional encoding
        pe_learnable = PositionalEncoding(
            d_model=d_model, max_len=max_len, learnable=True
        )
        out_learnable = pe_learnable(x)
        assert out_learnable.shape == (3, 10, d_model), "Learnable output shape is wrong."

        # get_positional_embeddings
        emb = pe.get_positional_embeddings(10)
        assert emb.shape == (10, d_model), "Non-learnable embeddings shape is wrong."
        emb_learnable = pe_learnable.get_positional_embeddings(10)
        assert emb_learnable.shape == (10, d_model), "Learnable embeddings shape is wrong."

        # Learned embeddings must update during training
        original_learned = pe_learnable.positional_embeddings.detach().clone()
        optimizer = torch.optim.SGD(pe_learnable.parameters(), lr=0.1)
        loss = pe_learnable(x).sum()
        loss.backward()
        optimizer.step()
        assert not torch.equal(
            pe_learnable.positional_embeddings, original_learned
        ), "Learned positional embeddings did not update."

        # Non-learned embeddings must stay fixed
        original_fixed = pe.pe.detach().clone()
        fixed_loss = pe(x).sum()
        fixed_loss.backward()
        assert torch.equal(pe.pe, original_fixed), "Fixed positional encoding changed."

        # Variable sequence lengths
        x_short = torch.randn(2, 5, d_model)
        out_short = pe(x_short)
        assert out_short.shape == (2, 5, d_model), "Variable length output shape is wrong."
        emb_short = pe.get_positional_embeddings(5)
        assert emb_short.shape == (5, d_model), "Variable length embeddings shape is wrong."

        # Scaling factor
        pe_scaled = PositionalEncoding(
            d_model=d_model, max_len=max_len, scaling=2.0, learnable=False
        )
        scaled_emb = pe_scaled.get_positional_embeddings(10)
        assert torch.allclose(scaled_emb, emb * 2.0), "Scaling factor not applied correctly."

        # API documentation
        assert PositionalEncoding.__doc__, "Class docstring missing."
        assert PositionalEncoding.forward.__doc__, "forward docstring missing."
        assert PositionalEncoding.get_positional_embeddings.__doc__, "get_positional_embeddings docstring missing."

        print("All _selftest assertions passed.")


if __name__ == "__main__":
    _selftest()
