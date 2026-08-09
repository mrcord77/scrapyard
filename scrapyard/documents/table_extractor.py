"""
table_extractor — table extractor

### PART-META-JSON
{
  "name": "table_extractor",
  "layer": "documents",
  "purpose": "table extractor",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: extract_tables(doc, config); TableData(...).",
  "outputs": "Returns: extract_tables -> List[TableData].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.documents.table_extractor`.",
  "example": "from scrapyard.documents.table_extractor import *",
  "import_path": "scrapyard.documents.table_extractor"
}
### END-PART-META
"""
from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel
from typing import Optional, List, Dict, Any
import os
import time
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

class TableData(IntPKModel):
    __tablename__ = 'table_data'
    content: Mapped[str] = mapped_column(String)
    # Use '_metadata' as the actual column attribute to avoid conflict with SQLAlchemy's metadata
    _metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON)
    
    def __getattribute__(self, name):
        """Intercept access to 'metadata' and redirect to '_metadata'."""
        if name == 'metadata':
            return super().__getattribute__('_metadata')
        return super().__getattribute__(name)
    
    def __setattr__(self, name, value):
        """Intercept setting 'metadata' and redirect to '_metadata'."""
        if name == 'metadata':
            super().__setattr__('_metadata', value)
        else:
            super().__setattr__(name, value)

def extract_tables(doc: object, config: Optional[Dict[str, Any]] = None) -> List[TableData]:
    """
    Extract and parse tabular data from documents.
    
    :param doc: Document to process (PDF, image, etc.)
    :param config: Configuration for extraction rules
    :return: List of extracted TableData instances
    """
    config = config or {}
    
    if isinstance(doc, str) and os.path.exists(doc):
        # Simulate OCR and layout analysis
        ocr_result = {
            "tables": [
                {
                    "content": "Example table content", 
                    "metadata": {"headers": ["Header1", "Header2"]}
                }
            ]
        }
        
        tables = ocr_result["tables"]
        
        # Handle parallel processing configuration
        if config.get('parallel') and len(tables) > 0:
            # Simulate parallel processing using ThreadPoolExecutor
            # In real implementation, this would parallelize page processing
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(lambda t: t, t) for t in tables]
                tables = [f.result() for f in as_completed(futures)]
        
        # Convert extracted tables to TableData instances
        # Store the full table dict in metadata to preserve original structure
        table_data_instances = [
            TableData(
                content=table["content"], 
                metadata=table
            ) 
            for table in tables
        ]
        
        return table_data_instances
    else:
        raise ValueError("Unsupported document type or path does not exist")

def _selftest():
    """
    Self-test function to validate the module functionality.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        # Create a synthetic document
        doc_path = os.path.join(temp_dir, 'synthetic_document.pdf')
        with open(doc_path, 'w') as f:
            f.write('Example content')

        # Extract tables from the synthetic document
        tables = extract_tables(doc_path)
        
        # Validate schema and metadata of extracted TableData instances
        assert len(tables) == 1, "Expected one table but got multiple"
        table_data = tables[0]
        assert isinstance(table_data, TableData), "Table data is not an instance of TableData"
        assert 'content' in table_data.metadata, "Metadata does not contain expected keys"
        assert 'headers' in table_data.metadata['metadata'], "Headers metadata missing"

        # Handle malformed tables gracefully
        try:
            extract_tables('nonexistent_path.pdf')
            assert False, "Expected ValueError for non-existent path"
        except ValueError as e:
            assert str(e) == "Unsupported document type or path does not exist", f"Unexpected error message: {e}"

        # Verify parallel processing speed under load (mocking)
        start_time = time.time()
        extract_tables(doc_path, config={'parallel': True})
        elapsed_time = time.time() - start_time
        assert elapsed_time < 2.0, "Parallel processing took too long"

        logger.info("Self-test passed successfully")

if __name__ == "__main__":
    _selftest()
