"""
parquet_dataset_loader — ** The `scrapyard.ml.parquet_dataset_loader` module provides efficient, reusable tools for loading large Parquet datasets in machine learning workflows. It ensures scalability, flexibility, and compat

### PART-META-JSON
{
  "name": "parquet_dataset_loader",
  "layer": "ml",
  "purpose": "Provides efficient, reusable tools for loading large Parquet datasets in machine learning workflows. It ensures scalability, flexibility, and compat.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: load_parquet(file_path, batch_size, parallel); ParquetLoader(...).",
  "outputs": "Returns: load_parquet -> Iterator[pd.DataFrame].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.parquet_dataset_loader`.",
  "example": "from scrapyard.ml.parquet_dataset_loader import *",
  "import_path": "scrapyard.ml.parquet_dataset_loader"
}
### END-PART-META
"""
import os
from typing import Iterator
import logging
import pandas as pd
import pyarrow.parquet as pq

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_parquet(file_path: str, batch_size: int = 1000, parallel: bool = False) -> Iterator[pd.DataFrame]:
    """
    Load a Parquet file into DataFrames in batches.
    
    :param file_path: Path to the Parquet file
    :param batch_size: Number of rows per batch
    :param parallel: Whether to load data in parallel (currently not supported)
    :return: Iterator yielding DataFrames
    """
    if parallel:
        logger.warning("Parallel loading is currently not supported.")
    
    with pq.ParquetFile(file_path) as parquet_file:
        for batch in parquet_file.iter_batches(batch_size=batch_size):
            yield batch.to_pandas()

class ParquetLoader:
    def __init__(self, file_path: str, batch_size: int = 1000):
        """
        Initialize the ParquetLoader with a file path and optional batch size.
        
        :param file_path: Path to the Parquet file
        :param batch_size: Number of rows per batch
        """
        self.file_path = file_path
        self.batch_size = batch_size

    def load(self, parallel: bool = False) -> Iterator[pd.DataFrame]:
        """
        Load the Parquet file in batches.
        
        :param parallel: Whether to load data in parallel (currently not supported)
        :return: Iterator yielding DataFrames
        """
        if parallel:
            logger.warning("Parallel loading is currently not supported.")
        
        with pq.ParquetFile(self.file_path) as parquet_file:
            for batch in parquet_file.iter_batches(batch_size=self.batch_size):
                yield batch.to_pandas()

def _selftest():
    import tempfile
    
    # Create a temporary directory and Parquet file
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        sample_data = pd.DataFrame({
            'id': range(10000),
            'value': [f'value_{i}' for i in range(10000)]
        })
        
        # Write the DataFrame to a Parquet file
        parquet_file_path = os.path.join(tmp_dir, "sample.parquet")
        sample_data.to_parquet(parquet_file_path)
        
        # Test load_parquet function
        df_generator = load_parquet(parquet_file_path, batch_size=1000)
        dfs = list(df_generator)
        assert len(dfs) == 10
        
        # Test ParquetLoader class
        loader = ParquetLoader(parquet_file_path, batch_size=500)
        df_generator_loader = loader.load()
        dfs_loader = list(df_generator_loader)
        assert len(dfs_loader) == 20

if __name__ == "__main__":
    _selftest()
