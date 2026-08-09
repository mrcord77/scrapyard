"""
deduplicator — ** The `deduplicator` module provides core functionality to eliminate duplicate records from datasets during data pipeline processing. It leverages transformation logic and ensures data integrity thro

### PART-META-JSON
{
  "name": "deduplicator",
  "layer": "data_eng",
  "purpose": "Eliminates duplicate records from pandas DataFrames during pipeline processing: applies a caller-supplied Transformer to every record first, then drops duplicates on the chosen key columns (keep-first). Includes a SQLAlchemy model used to demonstrate DB-side DISTINCT dedup. NOTE: sibling part data_io/data_deduplication covers the list-of-dicts (non-pandas) case with pluggable exact/fuzzy strategies - the two are intentionally separate, not duplicates of each other.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "pandas",
    "sqlalchemy",
    "scrapyard.database.base_model"
  ],
  "inputs": "A pandas DataFrame, key column names to deduplicate on, and a Transformer subclass instance (transform(record_dict) -> dict) applied before comparison.",
  "outputs": "A new deduplicated DataFrame (keep-first on key columns), index reset; input is not mutated.",
  "files_created": [],
  "security_notes": "Pure in-memory processing; no network, subprocess, or secret handling. Deduplication silently DROPS rows - when the pipeline feeds audit or billing data, log row counts before/after so deletions are accountable. The Transformer runs caller code over every record; supply only trusted transformer implementations. Keep-first ordering means input order decides which record survives a collision - sort deliberately upstream if that matters.",
  "ai_usage": "Subclass Transformer with your normalization, then remove_duplicates(df, ['key_col'], MyTransformer()). For list-of-dicts data use scrapyard.data_io.data_deduplication instead.",
  "example": "from scrapyard.data_eng.deduplicator import remove_duplicates, Transformer",
  "import_path": "scrapyard.data_eng.deduplicator"
}
### END-PART-META
"""
from sqlalchemy import String, Integer, func, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from dataclasses import dataclass
from typing import List, Dict, Any
import abc
import os, logging, tempfile
import pandas as pd

logger = logging.getLogger(__name__)

@dataclass
class Transformer(abc.ABC):
    @abc.abstractmethod
    def transform(self, record: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses should implement this method")

def remove_duplicates(
    data: pd.DataFrame,
    key_columns: List[str],
    transformer: Transformer,
) -> pd.DataFrame:
    """
    Remove duplicates from data based on key columns after applying transformation.
    
    Args:
        data: Input DataFrame
        key_columns: List of column names to use for deduplication
        transformer: Transformer instance to apply to each record before deduplication
    
    Returns:
        DataFrame with duplicates removed
    """
    if data.empty:
        return data.copy()
    
    # Apply transformer to each record (convert row to dict first)
    transformed_records = []
    for _, row in data.iterrows():
        record_dict = row.to_dict()
        transformed_record = transformer.transform(record_dict)
        transformed_records.append(transformed_record)
    
    # Create DataFrame from transformed records
    transformed_df = pd.DataFrame(transformed_records)
    
    # Remove duplicates based on key columns, keeping first occurrence
    deduplicated_df = transformed_df.drop_duplicates(subset=key_columns, keep='first').reset_index(drop=True)
    
    return deduplicated_df

class DeduplicationModel(IntPKModel):
    __tablename__ = 'deduplication_records'
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)

def _selftest():
    """Self-test for the deduplicator module."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting deduplicator self-test")
    
    # Test data setup
    data = pd.DataFrame({
        'id': [1, 2, 3, 4, 5],
        'name': ['Alice', 'Bob', 'Alice', 'Charlie', 'Bob'],
        'age': [25, 30, 25, 35, 30]
    })
    
    class MockTransformer(Transformer):
        def transform(self, record: Dict[str, Any]) -> Dict[str, Any]:
            """Convert all values to strings to verify transformer is applied."""
            return {k: str(v) for k, v in record.items()}
    
    # Test 1: Deduplication reduces row count correctly
    result_df = remove_duplicates(data, ['name'], MockTransformer())
    assert len(result_df) == 3, f"Deduplication failed: expected 3 rows, got {len(result_df)}"
    logger.info("Row count reduction verified")
    
    # Test 2: Transformer is applied before deduplication
    assert isinstance(result_df.iloc[0]['age'], str), "Transformer not applied: age should be string"
    assert isinstance(result_df.iloc[0]['id'], str), "Transformer not applied: id should be string"
    logger.info("Transformer application verified")
    
    # Test 3: No data loss - all unique names are preserved
    result_names = set(result_df['name'])
    expected_names = {'Alice', 'Bob', 'Charlie'}
    assert result_names == expected_names, f"Data loss: expected {expected_names}, got {result_names}"
    logger.info("No data loss verified")
    
    # Test 4: Database-backed deduplication with SQLite
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        try:
            # Create tables
            DeduplicationModel.metadata.create_all(engine)
            
            # Insert data
            with Session(engine) as session:
                for _, row in data.iterrows():
                    record = DeduplicationModel(
                        source_id=int(row['id']),
                        name=str(row['name']),
                        age=int(row['age'])
                    )
                    session.add(record)
                session.commit()
                
                # Verify database deduplication via distinct query
                stmt = select(func.distinct(DeduplicationModel.name))
                distinct_names = session.execute(stmt).scalars().all()
                assert len(distinct_names) == 3, f"DB deduplication failed: expected 3 distinct names, got {len(distinct_names)}"
                assert set(distinct_names) == expected_names, f"DB distinct names mismatch: {distinct_names}"
        finally:
            engine.dispose()
    
    logger.info("Self-test passed successfully")

if __name__ == "__main__":
    _selftest()
