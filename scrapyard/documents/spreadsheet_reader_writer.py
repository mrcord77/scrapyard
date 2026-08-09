"""
spreadsheet_reader_writer — ** The `spreadsheet_reader_writer` module provides reusable functionality for reading from and writing to Excel and CSV files using pandas, enabling seamless integration with data processing pipelines

### PART-META-JSON
{
  "name": "spreadsheet_reader_writer",
  "layer": "documents",
  "purpose": "Provides reusable functionality for reading from and writing to Excel and CSV files using pandas, enabling seamless integration with data processing pipelines.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: read_spreadsheet(file_path, format); write_spreadsheet(df, file_path, format); Spreadsheet(...).",
  "outputs": "Returns: read_spreadsheet -> pd.DataFrame.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.documents.spreadsheet_reader_writer`.",
  "example": "from scrapyard.documents.spreadsheet_reader_writer import *",
  "import_path": "scrapyard.documents.spreadsheet_reader_writer"
}
### END-PART-META
"""
import os
import pandas as pd

def read_spreadsheet(file_path: str, format: str = "xlsx") -> pd.DataFrame:
    if format.lower() == "xlsx":
        return pd.read_excel(file_path)
    elif format.lower() == "csv":
        return pd.read_csv(file_path)
    else:
        raise ValueError(f"Unsupported file format: {format}")

def write_spreadsheet(df: pd.DataFrame, file_path: str, format: str = "xlsx"):
    if format.lower() == "xlsx":
        df.to_excel(file_path, index=False)
    elif format.lower() == "csv":
        df.to_csv(file_path, index=False)
    else:
        raise ValueError(f"Unsupported file format: {format}")

class Spreadsheet:
    def __init__(self, data: pd.DataFrame):
        self.data = data

    def to_file(self, file_path: str, format: str = "xlsx"):
        if format.lower() == "xlsx":
            self.data.to_excel(file_path, index=False)
        elif format.lower() == "csv":
            self.data.to_csv(file_path, index=False)
        else:
            raise ValueError(f"Unsupported file format: {format}")

def _selftest():
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        # Test reading an Excel file
        excel_file = os.path.join(temp_dir, "test.xlsx")
        df_excel = pd.DataFrame({
            'A': [1, 2, 3],
            'B': ['a', 'b', 'c']
        })
        df_excel.to_excel(excel_file, index=False)
        read_df_excel = read_spreadsheet(excel_file)
        assert read_df_excel.equals(df_excel), "Excel file reading failed"

        # Test writing to an Excel file
        output_excel_file = os.path.join(temp_dir, "output.xlsx")
        write_spreadsheet(read_df_excel, output_excel_file)
        df_output_excel = pd.read_excel(output_excel_file)
        assert read_df_excel.equals(df_output_excel), "Excel file writing failed"

        # Test reading a CSV file
        csv_file = os.path.join(temp_dir, "test.csv")
        df_csv = pd.DataFrame({
            'A': [1, 2, 3],
            'B': ['a', 'b', 'c']
        })
        df_csv.to_csv(csv_file, index=False)
        read_df_csv = read_spreadsheet(csv_file, format="csv")
        assert read_df_csv.equals(df_csv), "CSV file reading failed"

        # Test writing to a CSV file
        output_csv_file = os.path.join(temp_dir, "output.csv")
        write_spreadsheet(read_df_csv, output_csv_file, format="csv")
        df_output_csv = pd.read_csv(output_csv_file)
        assert read_df_csv.equals(df_output_csv), "CSV file writing failed"

        # Test Spreadsheet class
        spreadsheet = Spreadsheet(read_df_excel)
        spreadsheet.to_file(os.path.join(temp_dir, "spreadsheet.xlsx"))
        df_spreadsheet = pd.read_excel(os.path.join(temp_dir, "spreadsheet.xlsx"))
        assert read_df_excel.equals(df_spreadsheet), "Spreadsheet class failed"

if __name__ == "__main__":
    _selftest()
