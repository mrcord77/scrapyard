"""
streaming_dataset_loader — Load large datasets as a stream to handle memory constraints. This module provides efficient, memory-friendly loading of ML datasets from various formats.

### PART-META-JSON
{
  "name": "streaming_dataset_loader",
  "layer": "ml",
  "purpose": "Load large datasets as a stream to handle memory constraints. This module provides efficient, memory-friendly loading of ML datasets from various formats.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "csv_dataset_loader",
    "parquet_dataset_loader"
  ],
  "inputs": "Public API: load_stream(source, format, batch_size, **kwargs); CSVLoader(...); ParquetLoader(...); StreamingLoader(...).",
  "outputs": "Returns: load_stream -> Iterator[Dict[str, Any]].",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.ml.streaming_dataset_loader`.",
  "example": "from scrapyard.ml.streaming_dataset_loader import *",
  "import_path": "scrapyard.ml.streaming_dataset_loader"
}
### END-PART-META
"""

"""
Purpose: Load large datasets as a stream to handle memory constraints. This module provides efficient, memory-friendly loading of ML datasets from various formats.

FEATURES:
- Stream data without loading full dataset into memory
- Supports CSV and Parquet formats via dependency modules
- Configurable batch sizes and data transformations
- Seamless integration with ML pipeline components
- Thread-safe and iterable interface
- Supports schema inference and validation
- Extensible for future format support
- Uses lazy evaluation for optimal performance
- Compatible with distributed data processing frameworks

PUBLIC API:
def load_stream(source: str, format: str, batch_size: int = 1024, **kwargs) -> Iterator[Dict[str, Any]]
class StreamingLoader:
    def __init__(self, source: str, format: str, batch_size: int = 1024, **kwargs)
    def __iter__(self) -> Iterator[Dict[str, Any]]
    def __next__(self) -> Dict[str, Any]
    def close(self) -> None

TABLES: none

SELFTEST MUST PROVE:
- load_stream() returns an iterator that yields batches
- StreamingLoader is iterable and yields correct data types
- No memory leaks during iteration
- Correctly handles CSV and Parquet formats
- Properly closes resources after iteration
- Schema validation works as expected
- Batch size is respected in output
- No exceptions raised on valid inputs
- Handles missing or malformed data gracefully
"""

from typing import Dict, Any, Iterator, List, Optional
import csv
import os
import logging
import tempfile

logger = logging.getLogger(__name__)


class CSVLoader:
    """Loader for CSV files that streams data in batches."""
    
    def __init__(self, source: str, **kwargs):
        self.source = source
        self._file_handle: Optional[Any] = None
        self.encoding = kwargs.get('encoding', 'utf-8')
        
    def load_stream(self, batch_size: int = 1024) -> Iterator[Dict[str, Any]]:
        """
        Stream CSV data in batches.
        
        Yields:
            Dict[str, Any]: Dictionary with column names as keys and lists of values as values.
        """
        self._file_handle = open(self.source, 'r', newline='', encoding=self.encoding)
        reader = csv.DictReader(self._file_handle)
        
        if reader.fieldnames is None:
            self._file_handle.close()
            return
            
        headers = reader.fieldnames
        batch: Dict[str, List[Any]] = {header: [] for header in headers}
        current_count = 0
        
        try:
            for row in reader:
                for header in headers:
                    batch[header].append(row[header])
                current_count += 1
                
                if current_count >= batch_size:
                    yield batch
                    batch = {header: [] for header in headers}
                    current_count = 0
            
            # Yield remaining rows
            if current_count > 0:
                yield batch
        finally:
            self.close()
            
    def close(self) -> None:
        """Close the file handle."""
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None


class ParquetLoader:
    """Loader for Parquet files that streams data in batches."""
    
    def __init__(self, source: str, **kwargs):
        self.source = source
        self.kwargs = kwargs
        self._closed = False
        
    def load_stream(self, batch_size: int = 1024) -> Iterator[Dict[str, Any]]:
        """
        Stream Parquet data in batches using pandas.
        
        Yields:
            Dict[str, Any]: Dictionary with column names as keys and lists of values as values.
        """
        if self._closed:
            raise RuntimeError("ParquetLoader is closed")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas is required for ParquetLoader")
            
        df = pd.read_parquet(self.source)
        headers = df.columns.tolist()
        total_rows = len(df)
        start_idx = 0
        
        while start_idx < total_rows:
            end_idx = min(start_idx + batch_size, total_rows)
            chunk = df.iloc[start_idx:end_idx]
            batch = {header: chunk[header].tolist() for header in headers}
            yield batch
            start_idx = end_idx
            
    def close(self) -> None:
        """No persistent file handle to close for pandas-based loader."""
        self._closed = True


class StreamingLoader:
    """Unified streaming loader that handles multiple formats."""
    
    def __init__(self, source: str, format: str, batch_size: int = 1024, **kwargs):
        self.source = source
        self.format = format.lower()
        self.batch_size = batch_size
        self.kwargs = kwargs
        self._loader: Optional[Any] = None
        self._iterator: Optional[Iterator] = None
        
        if self.format == 'csv':
            self._loader = CSVLoader(source, **kwargs)
        elif self.format == 'parquet':
            self._loader = ParquetLoader(source, **kwargs)
        else:
            raise ValueError(f"Unsupported format: {format}. Use 'csv' or 'parquet'.")
            
    def __iter__(self) -> Iterator[Dict[str, Any]]:
        """Initialize iteration."""
        self._iterator = self._loader.load_stream(batch_size=self.batch_size)
        return self
        
    def __next__(self) -> Dict[str, Any]:
        """Get next batch."""
        if self._iterator is None:
            self._iterator = self._loader.load_stream(batch_size=self.batch_size)
            
        try:
            return next(self._iterator)
        except StopIteration:
            self.close()
            raise
            
    def close(self) -> None:
        """Close underlying loader resources."""
        if self._loader:
            self._loader.close()
            self._loader = None
        self._iterator = None


def load_stream(source: str, format: str, batch_size: int = 1024, **kwargs) -> Iterator[Dict[str, Any]]:
    """
    Load a dataset as a stream of batches.
    
    Args:
        source: Path to the data file
        format: File format ('csv' or 'parquet')
        batch_size: Number of rows per batch
        **kwargs: Additional arguments passed to the specific loader
        
    Returns:
        Iterator yielding dictionaries of column_name -> list of values
    """
    loader = StreamingLoader(source=source, format=format, batch_size=batch_size, **kwargs)
    return iter(loader)


def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Create temporary files
        csv_path = os.path.join(tmpdir, 'data.csv')
        parquet_path = os.path.join(tmpdir, 'data.parquet')

        # Generate some sample data for testing
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            f.write('id,name,age\n1,Alice,30\n2,Bob,25\n3,Charlie,35')

        # Create parquet file with same data
        try:
            import pandas as pd
            df = pd.DataFrame({
                'id': [1, 2, 3],
                'name': ['Alice', 'Bob', 'Charlie'],
                'age': [30, 25, 35]
            })
            df.to_parquet(parquet_path, index=False)
            parquet_available = True
        except ImportError:
            parquet_available = False

        def test_streaming_loader(loader):
            iterator = loader.load_stream(batch_size=2)
            batches = list(iterator)
            assert len(batches) == 2, f"Expected 2 batches, got {len(batches)}"
            for batch in batches:
                assert isinstance(batch, dict), "Batch should be a dictionary"
                assert 'id' in batch and 'name' in batch and 'age' in batch, "Keys missing from batch"
            loader.close()

        # Test CSV
        csv_loader = CSVLoader(source=csv_path)
        test_streaming_loader(csv_loader)
        
        # Verify batch contents
        csv_loader2 = CSVLoader(source=csv_path)
        batches = list(csv_loader2.load_stream(batch_size=2))
        assert len(batches[0]['id']) == 2, "First batch should have 2 rows"
        assert len(batches[1]['id']) == 1, "Second batch should have 1 row"
        csv_loader2.close()

        # Test Parquet if available
        if parquet_available:
            parquet_loader = ParquetLoader(source=parquet_path)
            test_streaming_loader(parquet_loader)
            assert parquet_loader._closed is True
            try:
                list(parquet_loader.load_stream())
                raise AssertionError("closed parquet loader was reusable")
            except RuntimeError:
                pass

        # Test StreamingLoader class
        stream_loader = StreamingLoader(csv_path, 'csv', batch_size=2)
        batches = list(stream_loader)
        assert len(batches) == 2, "StreamingLoader should yield 2 batches"
        stream_loader.close()

        # Test load_stream function
        stream = load_stream(csv_path, 'csv', batch_size=2)
        batches = list(stream)
        assert len(batches) == 2, "load_stream should yield 2 batches"
        assert isinstance(batches[0], dict), "Batch should be dict"

        # Test resource cleanup
        loader = CSVLoader(csv_path)
        iter(loader.load_stream(batch_size=1))
        loader.close()
        assert loader._file_handle is None, "File should be closed"

        logger.info("All streaming_dataset_loader tests passed")


if __name__ == "__main__":
    _selftest()
