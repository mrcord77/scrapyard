"""
text_dataset_loader — ** The `scrapyard.ml.text_dataset_loader` module provides a reusable, standardized interface for loading text datasets commonly used in natural language processing tasks. It ensures consistent data lo

### PART-META-JSON
{
  "name": "text_dataset_loader",
  "layer": "ml",
  "purpose": "Provides a reusable, standardized interface for loading text datasets commonly used in natural language processing tasks. It ensures consistent data lo.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: load_text(path, format, preprocess, **kwargs); TextLoader(...).",
  "outputs": "Returns: load_text -> List[str].",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.ml.text_dataset_loader`.",
  "example": "from scrapyard.ml.text_dataset_loader import *",
  "import_path": "scrapyard.ml.text_dataset_loader"
}
### END-PART-META
"""
# PART-META-JSON: {"name": "scrapyard.ml.text_dataset_loader", "layer": "ml"}

import os
import logging
import tempfile
import sqlite3
from typing import Optional, List, Callable

import pandas as pd


logger = logging.getLogger(__name__)


def load_text(
    path: str,
    format: str = "auto",
    preprocess: Optional[Callable] = None,
    **kwargs
) -> List[str]:
    """
    Load text data from a local file or remote URL.

    :param path: Path to the file or URL.
    :param format: Format of the file (csv, json, txt, parquet). Defaults to 'auto'.
    :param preprocess: Preprocessing function to apply on loaded data.
    :param kwargs: Additional keyword arguments for specific formats.
    :return: List of text strings.
    """
    if format == "auto":
        _, ext = os.path.splitext(path)
        format = ext[1:].lower()

    if format in ["csv", "json"]:
        df = pd.read_csv(path) if format == "csv" else pd.read_json(path, **kwargs)
        texts = list(df.iloc[:, 0])
    elif format == "txt":
        with open(path, 'r', encoding='utf-8') as f:
            texts = [line.strip() for line in f.readlines()]
    elif format == "parquet":
        df = pd.read_parquet(path)
        texts = list(df.iloc[:, 0])
    else:
        raise ValueError(f"Unsupported file format: {format}")

    if preprocess:
        texts = preprocess(texts)

    return texts


class TextLoader:
    def __init__(self, path: str, format: str = "auto"):
        """
        Initialize the TextLoader with a path and optional format.

        :param path: Path to the file or URL.
        :param format: Format of the file (csv, json, txt, parquet). Defaults to 'auto'.
        """
        self.path = path
        self.format = format

    def load(self, preprocess: Optional[Callable] = None) -> List[str]:
        """
        Load and optionally preprocess text data.

        :param preprocess: Preprocessing function to apply on loaded data.
        :return: List of text strings.
        """
        return load_text(self.path, self.format, preprocess)


def _selftest():
    """Offline self-test using temporary files and SQLite."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Create test CSV
        csv_path = os.path.join(tmpdir, "test.csv")
        df_csv = pd.DataFrame({"text": ["hello world", "test data", "third line"]})
        df_csv.to_csv(csv_path, index=False)
        
        # Create test JSON
        json_path = os.path.join(tmpdir, "test.json")
        df_json = pd.DataFrame({"content": ["json line 1", "json line 2"]})
        df_json.to_json(json_path, orient='records')
        
        # Create test TXT
        txt_path = os.path.join(tmpdir, "test.txt")
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write("line one\nline two\nline three\n")
        
        # Create test Parquet
        parquet_path = os.path.join(tmpdir, "test.parquet")
        df_parquet = pd.DataFrame({"data": ["parquet one", "parquet two"]})
        df_parquet.to_parquet(parquet_path, index=False)
        
        # Test load_text with CSV
        texts = load_text(csv_path, format='csv')
        assert len(texts) == 3, f"Expected 3 texts from CSV, got {len(texts)}"
        assert texts[0] == "hello world"
        
        # Test TextLoader with CSV
        loader = TextLoader(csv_path, format='csv')
        texts = loader.load()
        assert len(texts) == 3, f"Expected 3 texts from TextLoader, got {len(texts)}"
        
        # Test TXT format
        texts = load_text(txt_path, format='txt')
        assert len(texts) == 3, f"Expected 3 texts from TXT, got {len(texts)}"
        assert texts[0] == "line one"
        
        # Test preprocessing function
        def preprocess(texts: List[str]) -> List[str]:
            return [t.upper() for t in texts]
        texts = load_text(csv_path, format='csv', preprocess=preprocess)
        assert all(t.isupper() for t in texts), "Preprocessing should convert to uppercase"
        assert texts[0] == "HELLO WORLD"
        
        # Test auto-detection for JSON
        texts = load_text(json_path)  # Auto-detect from .json extension
        assert len(texts) == 2, f"Expected 2 texts from JSON auto-detect, got {len(texts)}"
        assert texts[0] == "json line 1"
        
        # Test auto-detection for Parquet
        texts = load_text(parquet_path)  # Auto-detect from .parquet extension
        assert len(texts) == 2, f"Expected 2 texts from Parquet auto-detect, got {len(texts)}"
        assert texts[0] == "parquet one"
        
        # Test auto-detection for TXT
        texts = load_text(txt_path)  # Auto-detect from .txt extension
        assert len(texts) == 3
        
        # Test SQLite integration (verify connection handling)
        db_path = os.path.join(tmpdir, "metadata.db")
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS dataset_meta (id INTEGER PRIMARY KEY, name TEXT)")
            cursor.execute("INSERT INTO dataset_meta (name) VALUES ('test_dataset')")
            conn.commit()
            cursor.execute("SELECT name FROM dataset_meta")
            result = cursor.fetchall()
            assert len(result) == 1
            assert result[0][0] == 'test_dataset'
        finally:
            conn.close()
        
        logger.info("Selftest passed successfully.")


if __name__ == "__main__":
    _selftest()
