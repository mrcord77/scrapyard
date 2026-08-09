"""
pivot_rollup_helpers — ** The `pivot_rollup_helpers` module provides reusable tools for generating pivot and roll-up tables, enabling efficient data aggregation and summarization in data analysis workflows. It builds on a d

### PART-META-JSON
{
  "name": "pivot_rollup_helpers",
  "layer": "data_eng",
  "purpose": "Provides reusable tools for generating pivot and roll-up tables, enabling efficient data aggregation and summarization in data analysis workflows. It builds on a d.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_pivot_table(df, values, index, aggfunc); rollup_data(df, group_by, aggfunc); DataFrameConvenience(...).",
  "outputs": "Returns: create_pivot_table -> pd.DataFrame; rollup_data -> pd.DataFrame.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.data_eng.pivot_rollup_helpers`.",
  "example": "from scrapyard.data_eng.pivot_rollup_helpers import *",
  "import_path": "scrapyard.data_eng.pivot_rollup_helpers"
}
### END-PART-META
"""
from dataclasses import dataclass
from typing import List
import pandas as pd
import os, logging, sqlite3, tempfile

logger = logging.getLogger(__name__)

@dataclass
class DataFrameConvenience:
    df: pd.DataFrame

def create_pivot_table(df: pd.DataFrame, values: str, index: str, aggfunc: str = "sum") -> pd.DataFrame:
    """
    Creates a pivot table from the given dataframe.
    
    :param df: Input pandas DataFrame
    :param values: Column name to aggregate
    :param index: Column name to use as index in pivot table
    :param aggfunc: Aggregation function (default is 'sum')
    :return: Pandas DataFrame representing the pivot table
    """
    return df.pivot_table(values=values, index=index, aggfunc=aggfunc)

def rollup_data(df: pd.DataFrame, group_by: List[str], aggfunc: str = "sum") -> pd.DataFrame:
    """
    Rolls up data in the dataframe based on the specified columns.
    
    :param df: Input pandas DataFrame
    :param group_by: List of column names to group by
    :param aggfunc: Aggregation function (default is 'sum')
    :return: Pandas DataFrame representing the rolled-up data
    """
    return df.groupby(group_by).agg(aggfunc).reset_index()

def _selftest():
    # Create a temporary SQLite database and session for testing
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        engine = sqlite3.connect(db_path)
        
        # Sample data to test the functions
        sample_data = {
            "category": ["A", "A", "B", "C", "C"],
            "value": [10, 40, 20, 30, 60]
        }
        df = pd.DataFrame(sample_data)
        
        # Test create_pivot_table
        pivot_df = create_pivot_table(df, values="value", index="category")
        expected_pivot = pd.DataFrame({"category": ["A", "B", "C"], "value": [50, 20, 90]})
        expected_pivot.set_index("category", inplace=True)
        assert pivot_df.equals(expected_pivot), "Pivot table creation failed"
        
        # Test rollup_data
        rolled_up_df = rollup_data(df, group_by=["category"], aggfunc="sum")
        expected_rollup = pd.DataFrame({"category": ["A", "B", "C"], "value": [50, 20, 90]})
        assert rolled_up_df.equals(expected_rollup), "Rollup data failed"
        
        logger.info("Self-test passed successfully")

if __name__ == "__main__":
    _selftest()
