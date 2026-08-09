"""
embedding_layer — The `scrapyard.ml.embedding_layer` module provides reusable, configurable embedding layer utilities for text and categorical data, enabling seamless integration into neural network architectures. It i

### PART-META-JSON
{
  "name": "embedding_layer",
  "layer": "ml",
  "purpose": "The `scrapyard.ml.embedding_layer` module provides reusable, configurable embedding layer utilities for text and categorical data, enabling seamless integration into neural network architectures. It i",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_embedding(input_data, max_vocab, min_freq, tokenizer); EmbeddingLayer(...).",
  "outputs": "Returns: create_embedding -> Tuple[Any, Dict[str, int]].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.embedding_layer`.",
  "example": "from scrapyard.ml.embedding_layer import *",
  "import_path": "scrapyard.ml.embedding_layer"
}
### END-PART-META
"""

from typing import Optional, List, Dict, Any, Callable, Union, Tuple
import os
import json
import time
import logging
import sqlite3
import tempfile
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingLayer:
    """
    Factory for creating PyTorch embedding layers with configurable initialization
    and trainability. Returns a torch.nn.Embedding instance (nn.Module).
    """
    
    def __new__(
        cls,
        vocab_size: int,
        embedding_dim: int,
        trainable: bool = True,
        initializer: str = "glorot_uniform"
    ):
        import torch.nn as nn
        
        if vocab_size <= 0:
            raise ValueError(f"vocab_size must be positive, got {vocab_size}")
        if embedding_dim <= 0:
            raise ValueError(f"embedding_dim must be positive, got {embedding_dim}")
        
        embedding = nn.Embedding(vocab_size, embedding_dim)
        
        if initializer == "glorot_uniform":
            nn.init.xavier_uniform_(embedding.weight)
        elif initializer == "glorot_normal":
            nn.init.xavier_normal_(embedding.weight)
        elif initializer == "uniform":
            nn.init.uniform_(embedding.weight, -0.05, 0.05)
        elif initializer == "normal":
            nn.init.normal_(embedding.weight, 0, 0.01)
        elif initializer == "zeros":
            nn.init.zeros_(embedding.weight)
        else:
            nn.init.xavier_uniform_(embedding.weight)
        
        embedding.weight.requires_grad = trainable
        return embedding


def _default_tokenizer(text: str) -> List[str]:
    """Default whitespace tokenizer."""
    return text.split()


def create_embedding(
    input_data: Union[List[str], np.ndarray],
    max_vocab: Optional[int] = None,
    min_freq: Optional[int] = None,
    tokenizer: Optional[Callable[[str], List[str]]] = None
) -> Tuple[Any, Dict[str, int]]:
    """
    Creates an embedding layer from input data with built-in vocabulary construction.
    """
    
    if tokenizer is None:
        tokenizer = _default_tokenizer
    
    freq_dict: Dict[str, int] = {}
    
    if isinstance(input_data, np.ndarray):
        for item in input_data.flatten():
            token = str(item)
            freq_dict[token] = freq_dict.get(token, 0) + 1
    else:
        for text in input_data:
            if not isinstance(text, str):
                text = str(text)
            for token in tokenizer(text):
                freq_dict[token] = freq_dict.get(token, 0) + 1
    
    if min_freq is not None and min_freq > 1:
        freq_dict = {k: v for k, v in freq_dict.items() if v >= min_freq}
    
    sorted_items = sorted(freq_dict.items(), key=lambda x: (-x[1], x[0]))
    
    if max_vocab is not None and max_vocab > 0:
        sorted_items = sorted_items[:max_vocab]
    
    vocab_mapping = {token: idx for idx, (token, _) in enumerate(sorted_items)}
    
    vocab_size = len(vocab_mapping)
    if vocab_size == 0:
        vocab_size = 1
        vocab_mapping = {"<UNK>": 0}
    
    embedding_dim = min(128, max(16, vocab_size * 2)) if vocab_size < 64 else 128
    
    embedding_layer = EmbeddingLayer(
        vocab_size=vocab_size,
        embedding_dim=embedding_dim,
        trainable=True,
        initializer="glorot_uniform"
    )
    
    return embedding_layer, vocab_mapping


def _selftest():
    """Offline self-test suite with temporary SQLite backend."""
    import torch
    
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        
        # Test EmbeddingLayer initialization
        layer = EmbeddingLayer(vocab_size=100, embedding_dim=64, trainable=True)
        assert isinstance(layer, torch.nn.Embedding)
        assert layer.num_embeddings == 100
        assert layer.embedding_dim == 64
        assert layer.weight.requires_grad is True
        
        # Test frozen weights
        frozen = EmbeddingLayer(vocab_size=50, embedding_dim=32, trainable=False, initializer="zeros")
        assert frozen.weight.requires_grad is False
        assert torch.allclose(frozen.weight, torch.zeros_like(frozen.weight))
        
        # Test create_embedding with text
        texts = ["the quick brown fox", "the lazy dog", "quick brown dog", "the fox jumps"]
        emb, vocab = create_embedding(texts)
        assert isinstance(emb, torch.nn.Embedding)
        assert "the" in vocab
        assert "quick" in vocab
        assert isinstance(vocab["the"], int)
        
        # Test custom tokenizer
        def upper_tokenizer(text):
            return text.upper().split()
        emb2, vocab2 = create_embedding(["hello world"], tokenizer=upper_tokenizer)
        assert "HELLO" in vocab2
        assert "WORLD" in vocab2
        
        # Test max_vocab
        emb3, vocab3 = create_embedding(["a b c d e f g h i j"], max_vocab=3)
        assert len(vocab3) <= 3
        
        # Test min_freq
        texts_freq = ["common rare common", "common common rare", "common unique"]
        emb4, vocab4 = create_embedding(texts_freq, min_freq=2)
        assert "common" in vocab4
        assert "rare" in vocab4
        assert "unique" not in vocab4
        
        # Test numpy input
        arr = np.array([["x", "y"], ["x", "z"]])
        emb5, vocab5 = create_embedding(arr)
        assert "x" in vocab5 and "y" in vocab5 and "z" in vocab5
        
        # Test SQLite integration
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, vocab TEXT)")
        cursor.execute("INSERT INTO test (vocab) VALUES (?)", (json.dumps(vocab),))
        conn.commit()
        cursor.execute("SELECT vocab FROM test")
        loaded = json.loads(cursor.fetchone()[0])
        assert loaded == vocab
        cursor.close()
        conn.close()
        
        elapsed = time.time() - start_time
        assert elapsed < 20, f"Selftest took {elapsed}s"
        logger.info(f"embedding_layer selftest passed in {elapsed:.2f}s")
        return True


if __name__ == "__main__":
    _selftest()
