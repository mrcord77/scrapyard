"""
dataframe_convenience_layer — Provides reusable, high-level dataframe operations for data analysis, reducing boilerplate and improving consistency across projects. Functions are designed to be flexible, type-safe, and compatible w

### PART-META-JSON
{
  "name": "dataframe_convenience_layer",
  "layer": "data_eng",
  "purpose": "Provides reusable, high-level dataframe operations for data analysis, reducing boilerplate and improving consistency across projects. Functions are designed to be flexible, type-safe, and compatible w",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: read_csv(file_path, **kwargs); df_groupby_summarize(df, by, agg); pivot_table(df, values, index, columns).",
  "outputs": "Returns: read_csv -> pd.DataFrame; df_groupby_summarize -> pd.DataFrame; pivot_table -> pd.DataFrame.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.data_eng.dataframe_convenience_layer`.",
  "example": "from scrapyard.data_eng.dataframe_convenience_layer import *",
  "import_path": "scrapyard.data_eng.dataframe_convenience_layer"
}
### END-PART-META
"""

from typing import List, Dict
import pandas as pd
import tempfile
import os

def read_csv(file_path: str, **kwargs) -> pd.DataFrame:
    """
    Load a CSV file into a DataFrame.
    
    Parameters:
        file_path (str): Path to the CSV file.
        kwargs: Additional arguments passed to pandas.read_csv.
        
    Returns:
        pd.DataFrame: The loaded DataFrame.
    """
    return pd.read_csv(file_path, **kwargs)

def df_groupby_summarize(df: pd.DataFrame, by: List[str], agg: Dict[str, str]) -> pd.DataFrame:
    """
    Group the DataFrame and perform aggregations as specified.
    
    Parameters:
        df (pd.DataFrame): The input DataFrame.
        by (List[str]): Columns to group by.
        agg (Dict[str, str]): Aggregation dictionary where keys are column names
                              and values are aggregation functions ('sum', 'mean', etc.).
                              
    Returns:
        pd.DataFrame: The summarized DataFrame.
    """
    return df.groupby(by).agg(agg)

def pivot_table(df: pd.DataFrame, values: str, index: List[str], columns: str) -> pd.DataFrame:
    """
    Create a pivot table from the DataFrame.
    
    Parameters:
        df (pd.DataFrame): The input DataFrame.
        values (str): Column to aggregate.
        index (List[str]): Columns to use to make new frame's index.
        columns (str): Column to group data by creating a MultiIndex for the pivot table.
        
    Returns:
        pd.DataFrame: The pivoted DataFrame.
    """
    if df.empty:
        raise ValueError("DataFrame is empty")
    required_cols = [values, columns] + list(index)
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    return df.pivot_table(values=values, index=index, columns=columns)

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Create sample CSV file
        csv_path = os.path.join(tmpdir, 'sample_data.csv')
        with open(csv_path, 'w') as f:
            f.write("category,subcategory,value\n")
            f.write("A,X,10\n")
            f.write("A,Y,20\n")
            f.write("B,X,30\n")
            f.write("B,Y,40\n")
        
        # Test read_csv
        sample_df = read_csv(csv_path)
        assert isinstance(sample_df, pd.DataFrame), "read_csv should return a pandas DataFrame"
        assert len(sample_df) == 4, "Sample DataFrame should have 4 rows"
        
        # Test df_groupby_summarize
        by_columns = ['category']
        agg_dict = {'value': 'sum'}
        grouped_df = df_groupby_summarize(sample_df, by=by_columns, agg=agg_dict)
        assert isinstance(grouped_df, pd.DataFrame), "df_groupby_summarize should return a pandas DataFrame"
        assert grouped_df.loc['A', 'value'] == 30, "Category A should sum to 30"
        assert grouped_df.loc['B', 'value'] == 70, "Category B should sum to 70"
        
        # Test pivot_table
        values_column = 'value'
        index_columns = ['category']
        columns_column = 'subcategory'
        pivoted_df = pivot_table(sample_df, values=values_column, index=index_columns, columns=columns_column)
        assert isinstance(pivoted_df, pd.DataFrame), "pivot_table should return a pandas DataFrame"
        assert pivoted_df.loc['A', 'X'] == 10, "Pivot value A,X should be 10"
        assert pivoted_df.loc['B', 'Y'] == 40, "Pivot value B,Y should be 40"
        
        # Ensure all functions raise appropriate exceptions on invalid inputs
        try:
            read_csv(os.path.join(tmpdir, 'nonexistent_file.csv'))
            assert False, "read_csv should raise FileNotFoundError for non-existent files"
        except FileNotFoundError:
            pass
        
        try:
            df_groupby_summarize(pd.DataFrame(), by=[], agg={})
            assert False, "df_groupby_summarize should raise ValueError with empty DataFrame or invalid inputs"
        except (ValueError, KeyError):
            pass
        
        try:
            pivot_table(pd.DataFrame(), values='value', index=['category'], columns='subcategory')
            assert False, "pivot_table should raise ValueError with empty DataFrame or invalid inputs"
        except ValueError:
            pass

if __name__ == "__main__":
    _selftest()
