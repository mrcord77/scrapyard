"""
attention_block — ** The `scrapyard.ml.attention_block` module provides reusable attention mechanisms for neural networks, enabling flexible integration into various deep learning architectures. It is designed to be mo

### PART-META-JSON
{
  "name": "attention_block",
  "layer": "ml",
  "purpose": "Provides reusable attention mechanisms for neural networks, enabling flexible integration into various deep learning architectures. It is designed to be mo.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: SelfAttention(...); MultiHeadAttention(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.attention_block`.",
  "example": "from scrapyard.ml.attention_block import *",
  "import_path": "scrapyard.ml.attention_block"
}
### END-PART-META
"""
import torch
from torch import nn

class SelfAttention(nn.Module):
    def __init__(self, embed_dim: int, dropout: float = 0.1) -> None:
        super(SelfAttention, self).__init__()
        self.query = nn.Linear(embed_dim, embed_dim)
        self.key = nn.Linear(embed_dim, embed_dim)
        self.value = nn.Linear(embed_dim, embed_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        query = self.query(x)
        key = self.key(x).transpose(-2, -1)
        value = self.value(x)

        scores = torch.matmul(query, key) / (x.size(-1) ** 0.5)
        attention_weights = nn.functional.softmax(scores, dim=-1)
        attention_output = torch.matmul(attention_weights, value)
        attention_output = self.dropout(attention_output)

        return attention_output

class MultiHeadAttention(nn.Module):
    def __init__(self, embed_dim: int, num_heads: int, dropout: float = 0.1) -> None:
        super(MultiHeadAttention, self).__init__()
        assert embed_dim % num_heads == 0, "Embedding dimension must be divisible by number of heads"
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads

        self.query = nn.Linear(embed_dim, embed_dim)
        self.key = nn.Linear(embed_dim, embed_dim)
        self.value = nn.Linear(embed_dim, embed_dim)
        self.out = nn.Linear(embed_dim, embed_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, seq_len, _ = x.size()

        query = self.query(x).view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)
        key = self.key(x).view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)
        value = self.value(x).view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)

        scores = torch.matmul(query, key.transpose(-2, -1)) / (self.head_dim ** 0.5)
        attention_weights = nn.functional.softmax(scores, dim=-1)
        attention_output = torch.matmul(attention_weights, value).transpose(1, 2).contiguous().view(batch_size, seq_len, self.embed_dim)
        attention_output = self.dropout(self.out(attention_output))

        return attention_output

def _selftest() -> None:
    embed_dim = 64
    num_heads = 8
    dropout = 0.1
    batch_size = 2
    seq_len = 32

    # Test SelfAttention
    self_attention = SelfAttention(embed_dim, dropout)
    input_tensor = torch.randn(batch_size, seq_len, embed_dim)
    output_tensor = self_attention(input_tensor)
    assert output_tensor.shape == (batch_size, seq_len, embed_dim), "SelfAttention forward pass failed"

    # Test MultiHeadAttention
    multi_head_attention = MultiHeadAttention(embed_dim, num_heads, dropout)
    input_tensor = torch.randn(batch_size, seq_len, embed_dim)
    output_tensor = multi_head_attention(input_tensor)
    assert output_tensor.shape == (batch_size, seq_len, embed_dim), "MultiHeadAttention forward pass failed"

if __name__ == "__main__":
    _selftest()
