"""
dataset_splitter — ** The `scrapyard.ml.dataset_splitter` module provides flexible, reusable tools for splitting datasets into training, validation, and test sets, supporting multiple data formats. It ensures consistent

### PART-META-JSON
{
  "name": "dataset_splitter",
  "layer": "ml",
  "purpose": "Provides flexible, reusable tools for splitting datasets into training, validation, and test sets, supporting multiple data formats. It ensures consistent.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: split_dataset(data, split_ratios, seed, format); Splitter(...).",
  "outputs": "Returns: split_dataset -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.dataset_splitter`.",
  "example": "from scrapyard.ml.dataset_splitter import *",
  "import_path": "scrapyard.ml.dataset_splitter"
}
### END-PART-META
"""
# PART-META-JSON: {"name": "scrapyard.ml.dataset_splitter", "layer": "ml"}

from typing import Any, Dict, Optional
import os
import logging
import tempfile

import pandas as pd

logger = logging.getLogger(__name__)


def _load_data(data: Any, format: str) -> pd.DataFrame:
    """Load data from file path or return DataFrame if already in memory."""
    if isinstance(data, pd.DataFrame):
        return data.copy()
    
    if format == "csv":
        return pd.read_csv(data)
    elif format == "parquet":
        return pd.read_parquet(data)
    else:
        raise ValueError(f"Unsupported data format: {format}")


def split_dataset(
    data: Any,
    split_ratios: Dict[str, float],
    seed: Optional[int] = None,
    format: str = "csv"
) -> Dict[str, Any]:
    """
    Split dataset into train/val/test sets.
    
    Args:
        data: Path to data file, file-like object, or pandas DataFrame
        split_ratios: Dict with 'train', 'val', 'test' keys summing to 1.0
        seed: Random seed for reproducibility
        format: Data format ('csv' or 'parquet'), ignored if data is DataFrame
    
    Returns:
        Dictionary with 'train', 'val', 'test' DataFrames
    """
    df = _load_data(data, format)
    
    if not all(k in split_ratios for k in ("train", "val", "test")):
        raise ValueError("split_ratios must contain 'train', 'val', and 'test' keys")
    
    train_ratio = split_ratios["train"]
    val_ratio = split_ratios["val"]
    test_ratio = split_ratios["test"]
    
    if abs((train_ratio + val_ratio + test_ratio) - 1.0) > 1e-6:
        raise ValueError("Split ratios must sum to 1.0")
    
    n = len(df)
    if n == 0:
        empty_df = df.iloc[0:0]
        return {"train": empty_df, "val": empty_df, "test": empty_df}
    
    # Calculate split sizes
    train_size = int(n * train_ratio)
    val_size = int(n * val_ratio)
    test_size = n - train_size - val_size
    
    # Shuffle and split
    if seed is not None:
        shuffled = df.sample(frac=1, random_state=seed).reset_index(drop=True)
    else:
        shuffled = df.sample(frac=1).reset_index(drop=True)
    
    train_df = shuffled.iloc[:train_size]
    val_df = shuffled.iloc[train_size:train_size + val_size]
    test_df = shuffled.iloc[train_size + val_size:]
    
    return {
        "train": train_df,
        "val": val_df,
        "test": test_df
    }


class Splitter:
    """
    Dataset splitter supporting CSV and Parquet formats with reproducible splits.
    """
    
    def __init__(self, data: Any, format: str = "csv"):
        """
        Initialize Splitter.
        
        Args:
            data: File path or pandas DataFrame
            format: 'csv' or 'parquet', ignored if data is DataFrame
        """
        self.data = data
        self.format = format
    
    def split(self, split_ratios: Dict[str, float], seed: Optional[int] = None) -> Dict[str, Any]:
        """
        Execute dataset split.
        
        Args:
            split_ratios: Dict with 'train', 'val', 'test' ratios
            seed: Random seed for reproducibility
        
        Returns:
            Dictionary with 'train', 'val', 'test' DataFrames
        """
        return split_dataset(self.data, split_ratios, seed=seed, format=self.format)


def _selftest():
    """Offline self-test with temporary files."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        # Create test data
        csv_file = os.path.join(temp_dir, "test.csv")
        test_df = pd.DataFrame({
            'a': [1, 2, 3, 4, 5],
            'b': ['x', 'y', 'z', 'w', 'v']
        })
        test_df.to_csv(csv_file, index=False)
        
        parquet_file = os.path.join(temp_dir, "test.parquet")
        test_df.to_parquet(parquet_file, index=False)
        
        # Test CSV splitting
        splitter = Splitter(csv_file, format='csv')
        split_data = splitter.split({'train': 0.6, 'val': 0.2, 'test': 0.2}, seed=42)
        assert len(split_data['train']) == 3 and len(split_data['val']) == 1 and len(split_data['test']) == 1
        
        # Test Parquet splitting
        splitter = Splitter(parquet_file, format='parquet')
        split_data = splitter.split({'train': 0.6, 'val': 0.2, 'test': 0.2}, seed=42)
        assert len(split_data['train']) == 3 and len(split_data['val']) == 1 and len(split_data['test']) == 1
        
        # Test reproducibility
        split1 = Splitter(csv_file, format='csv').split({'train': 0.6, 'val': 0.2, 'test': 0.2}, seed=42)
        split2 = Splitter(csv_file, format='csv').split({'train': 0.6, 'val': 0.2, 'test': 0.2}, seed=42)
        assert split1['train'].equals(split2['train'])
        assert split1['val'].equals(split2['val'])
        assert split1['test'].equals(split2['test'])
        
        # Test function API
        result = split_dataset(csv_file, {'train': 0.6, 'val': 0.2, 'test': 0.2}, seed=42, format='csv')
        assert len(result['train']) == 3 and len(result['val']) == 1 and len(result['test']) == 1
        
        # Test in-memory DataFrame
        result_df = split_dataset(test_df, {'train': 0.6, 'val': 0.2, 'test': 0.2}, seed=42, format='csv')
        assert len(result_df['train']) == 3 and len(result_df['val']) == 1 and len(result_df['test']) == 1


if __name__ == "__main__":
    _selftest()
