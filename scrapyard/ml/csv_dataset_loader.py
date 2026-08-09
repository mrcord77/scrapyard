"""
csv_dataset_loader — The `csv_dataset_loader` module provides a flexible and efficient way to load CSV datasets into memory or as a stream, supporting large-scale data processing and integration with ML pipelines.

### PART-META-JSON
{
  "name": "csv_dataset_loader",
  "layer": "ml",
  "purpose": "The `csv_dataset_loader` module provides a flexible and efficient way to load CSV datasets into memory or as a stream, supporting large-scale data processing and integration with ML pipelines.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: load_csv(file_path, *, delimiter, encoding, chunksize); CSVLoader(...).",
  "outputs": "Returns: load_csv -> Union[pd.DataFrame, Iterator[pd.DataFrame]].",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.ml.csv_dataset_loader`.",
  "example": "from scrapyard.ml.csv_dataset_loader import *",
  "import_path": "scrapyard.ml.csv_dataset_loader"
}
### END-PART-META
"""

import os
import logging
import tempfile
import pandas as pd

from typing import Optional, Iterator, Union

logger = logging.getLogger(__name__)

def load_csv(file_path: str, *, delimiter: str = ",", encoding: str = "utf-8", chunksize: Optional[int] = None) -> Union[pd.DataFrame, Iterator[pd.DataFrame]]:
    """
    Load a CSV file into memory or as an iterator of DataFrames.
    
    :param file_path: Path to the CSV file.
    :param delimiter: Delimiter used in the CSV file.
    :param encoding: Encoding of the CSV file.
    :param chunksize: Number of rows per chunk if streaming is enabled.
    :return: A DataFrame or an iterator of DataFrames depending on chunksize.
    """
    try:
        if chunksize:
            return pd.read_csv(file_path, delimiter=delimiter, encoding=encoding, iterator=True, chunksize=chunksize)
        else:
            return pd.read_csv(file_path, delimiter=delimiter, encoding=encoding)
    except Exception as e:
        logger.error(f"Failed to load CSV file: {e}")
        raise

class CSVLoader:
    """
    A class for loading CSV files with customizable delimiters and encodings.
    
    :param file_path: Path to the CSV file.
    :param delimiter: Delimiter used in the CSV file.
    :param encoding: Encoding of the CSV file.
    """
    def __init__(self, file_path: str, delimiter: str = ",", encoding: str = "utf-8"):
        self.file_path = file_path
        self.delimiter = delimiter
        self.encoding = encoding

    def load(self, chunksize: Optional[int] = None) -> Union[pd.DataFrame, Iterator[pd.DataFrame]]:
        """
        Load the CSV file into memory or as an iterator of DataFrames.
        
        :param chunksize: Number of rows per chunk if streaming is enabled.
        :return: A DataFrame or an iterator of DataFrames depending on chunksize.
        """
        try:
            if chunksize:
                return pd.read_csv(self.file_path, delimiter=self.delimiter, encoding=self.encoding, iterator=True, chunksize=chunksize)
            else:
                return pd.read_csv(self.file_path, delimiter=self.delimiter, encoding=self.encoding)
        except Exception as e:
            logger.error(f"Failed to load CSV file: {e}")
            raise

def _selftest():
    """
    Self-test the module.
    
    :return: None
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        # Create a small test CSV file
        test_csv_path = os.path.join(temp_dir, 'test.csv')
        with open(test_csv_path, 'w', encoding='utf-8') as f:
            f.write('id,name,age\n1,Alice,30\n2,Bob,25')

        # Load the small CSV file into a DataFrame
        df = load_csv(test_csv_path)
        assert isinstance(df, pd.DataFrame), "Failed to load small CSV file"
        assert len(df) == 2, "Incorrect number of rows in DataFrame"

        # Stream a large CSV file in chunks (create a larger test file)
        with tempfile.NamedTemporaryFile(dir=temp_dir, delete=False, mode='w', encoding='utf-8') as f:
            for i in range(1000):
                f.write(f'{i},{chr(i%26 + ord("a"))},30\n')

        large_csv_path = f.name
        loader = CSVLoader(large_csv_path)
        chunks = list(loader.load(chunksize=10))
        assert len(chunks) == 100, "Incorrect number of chunks when streaming"

        # Handle malformed CSV with proper error logging (create a malformed test file)
        malformed_csv_path = os.path.join(temp_dir, 'malformed.csv')
        with open(malformed_csv_path, 'w', encoding='utf-8') as f:
            f.write('id,name,age\n1,Alice,302,Bob,25')

        try:
            load_csv(malformed_csv_path)
        except Exception as e:
            assert "malformed" in str(e), "Failed to handle malformed CSV"

if __name__ == "__main__":
    _selftest()
