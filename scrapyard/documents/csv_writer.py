"""
csv_writer — ** The `scrapyard.documents.csv_writer` module provides a robust and reusable interface for writing structured data to CSV files, ensuring compatibility, performance, and flexibility for document proc

### PART-META-JSON
{
  "name": "csv_writer",
  "layer": "documents",
  "purpose": "Provides a robust and reusable interface for writing structured data to CSV files, ensuring compatibility, performance, and flexibility for document proc.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: write_csv(file_path, data, **kwargs); CSVWriter(...).",
  "outputs": "Returns: write_csv -> None.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.documents.csv_writer`.",
  "example": "from scrapyard.documents.csv_writer import *",
  "import_path": "scrapyard.documents.csv_writer"
}
### END-PART-META
"""
import csv
import os
import tempfile
import time
import logging
from typing import Iterable, Dict, Any, Optional

logger = logging.getLogger(__name__)


def write_csv(file_path: str, data: Iterable[Dict[str, Any]], **kwargs) -> None:
    """
    Write an iterable of dictionaries to a CSV file.
    
    Args:
        file_path: Path to the output CSV file.
        data: Iterable of dictionaries representing rows.
        **kwargs: Additional arguments including:
            - encoding: File encoding (default: 'utf-8')
            - fieldnames: List of field names for header. Auto-detected from 
              first row if not provided.
            - dialect: CSV dialect to use (default: 'excel')
            - Other arguments passed to csv.DictWriter.
    """
    encoding = kwargs.pop('encoding', 'utf-8')
    fieldnames = kwargs.pop('fieldnames', None)
    
    iterator = iter(data)
    
    try:
        first_row = next(iterator)
    except StopIteration:
        # Empty data - write header only if fieldnames explicitly provided
        # Create file even if empty (no fieldnames, no data)
        with open(file_path, 'w', newline='', encoding=encoding) as f:
            if fieldnames:
                writer = csv.DictWriter(f, fieldnames=fieldnames, **kwargs)
                writer.writeheader()
        return
    
    if fieldnames is None:
        fieldnames = list(first_row.keys())
    
    with open(file_path, 'w', newline='', encoding=encoding) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, **kwargs)
        writer.writeheader()
        writer.writerow(first_row)
        writer.writerows(iterator)


class CSVWriter:
    """
    A reusable CSV writer supporting streaming data and custom configurations.
    """
    
    def __init__(self, file_path: str, **kwargs):
        """
        Initialize the CSVWriter.
        
        Args:
            file_path: Path to the output CSV file.
            **kwargs: Configuration options including:
                - encoding: File encoding (default: 'utf-8')
                - fieldnames: List of field names. Inferred from first write 
                  if not provided.
                - dialect: CSV dialect (default: 'excel')
                - Additional csv.DictWriter arguments.
        """
        self.file_path = file_path
        self._encoding = kwargs.pop('encoding', 'utf-8')
        self._fieldnames = kwargs.pop('fieldnames', None)
        self._writer_kwargs = kwargs
        self._file_handle: Optional[Any] = None
        self._writer: Optional[csv.DictWriter] = None
        self._header_written = False
    
    def _ensure_file_open(self) -> None:
        """Open the file handle if not already open."""
        if self._file_handle is None:
            self._file_handle = open(
                self.file_path, 
                'w', 
                newline='', 
                encoding=self._encoding
            )
    
    def write(self, data: Iterable[Dict[str, Any]]) -> None:
        """
        Write data to the CSV file. Can be called multiple times to append batches.
        
        Args:
            data: Iterable of dictionaries to write.
        """
        self._ensure_file_open()
        
        iterator = iter(data)
        try:
            first_row = next(iterator)
        except StopIteration:
            return
        
        # Determine fieldnames from first row if not preset
        if self._fieldnames is None:
            self._fieldnames = list(first_row.keys())
        
        # Initialize writer if needed
        if self._writer is None:
            self._writer = csv.DictWriter(
                self._file_handle,
                fieldnames=self._fieldnames,
                **self._writer_kwargs
            )
        
        # Write header once
        if not self._header_written:
            self._writer.writeheader()
            self._header_written = True
        
        # Write data
        self._writer.writerow(first_row)
        for row in iterator:
            self._writer.writerow(row)
    
    def close(self) -> None:
        """Close the file handle and release resources."""
        if self._file_handle is not None:
            self._file_handle.close()
            self._file_handle = None
            self._writer = None


def _selftest() -> None:
    """Offline self-test for the csv_writer module."""
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Test 1: write_csv basic functionality
        test_path = os.path.join(tmpdir, 'test_basic.csv')
        test_data = [
            {'name': 'Alice', 'age': '30', 'city': 'NYC'},
            {'name': 'Bob', 'age': '25', 'city': 'LA'},
        ]
        write_csv(test_path, test_data)
        
        with open(test_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 2
            assert rows[0]['name'] == 'Alice'
            assert rows[1]['city'] == 'LA'
        
        # Test 2: CSVWriter streaming with generator
        stream_path = os.path.join(tmpdir, 'test_stream.csv')
        writer = CSVWriter(stream_path)
        
        def data_generator():
            for i in range(100):
                yield {'id': str(i), 'square': str(i * i)}
        
        writer.write(data_generator())
        writer.close()
        
        with open(stream_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 100
            assert rows[50]['id'] == '50'
            assert rows[50]['square'] == '2500'
        
        # Test 3: Encoding support (UTF-8 with special characters)
        utf8_path = os.path.join(tmpdir, 'test_utf8.csv')
        utf8_data = [{'text': 'Héllo Wörld 你好', 'emoji': '🚀'}]
        write_csv(utf8_path, utf8_data, encoding='utf-8')
        
        with open(utf8_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert 'Héllo Wörld 你好' in content
            assert '🚀' in content
        
        # Test 4: Custom dialect (tab-separated)
        tab_path = os.path.join(tmpdir, 'test_tab.csv')
        write_csv(tab_path, [{'col1': 'a', 'col2': 'b'}], dialect='excel-tab')
        
        with open(tab_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert '\t' in content
            assert 'col1\tcol2' in content
        
        # Test 5: CSVWriter with explicit fieldnames ordering
        order_path = os.path.join(tmpdir, 'test_order.csv')
        writer2 = CSVWriter(order_path, fieldnames=['z', 'a', 'm'])
        writer2.write([{'a': '1', 'z': '2', 'm': '3'}])
        writer2.close()
        
        with open(order_path, 'r', encoding='utf-8') as f:
            header = f.readline().strip()
            assert header == 'z,a,m'
        
        # Test 6: Empty data handling
        empty_path = os.path.join(tmpdir, 'test_empty.csv')
        write_csv(empty_path, [])
        assert os.path.exists(empty_path)
        
        # Test 7: Multiple writes to same CSVWriter (streaming batches)
        batch_path = os.path.join(tmpdir, 'test_batch.csv')
        writer3 = CSVWriter(batch_path)
        writer3.write([{'x': '1'}])
        writer3.write([{'x': '2'}, {'x': '3'}])
        writer3.close()
        
        with open(batch_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 3
            assert rows[0]['x'] == '1'
            assert rows[2]['x'] == '3'
        
        # Test 8: Header-only when fieldnames provided but no data
        header_only_path = os.path.join(tmpdir, 'test_header_only.csv')
        write_csv(header_only_path, [], fieldnames=['a', 'b', 'c'])
        
        with open(header_only_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            assert len(lines) == 1
            assert lines[0].strip() == 'a,b,c'
    
    elapsed = time.time() - start_time
    assert elapsed < 20, f"Self-test took {elapsed}s, exceeding 20s limit"
    logger.info(f"csv_writer self-test completed in {elapsed:.2f}s")


if __name__ == '__main__':
    _selftest()
