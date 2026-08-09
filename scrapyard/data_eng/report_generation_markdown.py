"""
report_generation_markdown — ** Generates Markdown-formatted reports from data analysis results, enabling structured documentation of insights and findings. Integrates with HTML report generation and dataframe utilities for seaml

### PART-META-JSON
{
  "name": "report_generation_markdown",
  "layer": "data_eng",
  "purpose": "Generates Markdown-formatted reports from data analysis results, enabling structured documentation of insights and findings. Integrates with HTML report generation and dataframe utilities for seaml.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: generate_markdown_report(data, title, output_path); create_markdown_table(data, headers).",
  "outputs": "Returns: generate_markdown_report -> None; create_markdown_table -> str.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.data_eng.report_generation_markdown`.",
  "example": "from scrapyard.data_eng.report_generation_markdown import *",
  "import_path": "scrapyard.data_eng.report_generation_markdown"
}
### END-PART-META
"""
from typing import Any, List
import os
import logging
import sqlite3
import tempfile
import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_markdown_report(data: Any, title: str, output_path: str) -> None:
    """
    Generates a Markdown report from analysis results.
    
    :param data: Data to be included in the report (can be any serializable format).
    :param title: Title of the report.
    :param output_path: Path where the report will be saved.
    """
    if not isinstance(title, str) or not title:
        raise ValueError("Title must be a non-empty string.")
    
    if not os.path.isdir(os.path.dirname(output_path)):
        raise NotADirectoryError(f"Directory for {output_path} does not exist.")
    
    markdown_content = f"# {title}\n\n"
    if isinstance(data, pd.DataFrame):
        markdown_content += create_markdown_table(data, data.columns.tolist())
    else:
        markdown_content += str(data)
    
    with open(output_path, 'w', encoding='utf-8') as file:
        file.write(markdown_content)

def create_markdown_table(data: pd.DataFrame, headers: List[str]) -> str:
    """
    Converts a DataFrame to a Markdown table string.
    
    :param data: The DataFrame to convert.
    :param headers: Headers for the table columns.
    :return: A string representing the Markdown table.
    """
    if not isinstance(headers, list) or not all(isinstance(h, str) for h in headers):
        raise ValueError("Headers must be a list of strings.")
    
    if data.empty:
        return "No data to display."
    
    markdown_table = "| " + " | ".join(headers) + " |\n"
    markdown_table += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    for _, row in data.iterrows():
        markdown_table += "| " + " | ".join([str(row[h]) for h in headers]) + " |\n"
    
    return markdown_table

def _selftest() -> None:
    """
    Self-test the module to ensure it works as expected.
    """
    logger.info("Starting self-test...")
    
    # Create a temporary SQLite database and table
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        conn = sqlite3.connect(os.path.join(temp_dir, "test.db"))
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)')
        conn.commit()
        
        # Insert some data
        cursor.executemany('INSERT INTO test_table (name) VALUES (?)', [('Alice',), ('Bob',)])
        conn.commit()
        
        # Query the data and convert to DataFrame
        query = 'SELECT * FROM test_table'
        df = pd.read_sql_query(query, conn)
        
        # Generate a Markdown report
        output_path = os.path.join(temp_dir, "test_report.md")
        generate_markdown_report(df, "Test Report", output_path)
        
        with open(output_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        assert "# Test Report\n\n| id | name |\n| --- | --- |\n| 1 | Alice |\n| 2 | Bob |\n" in content
        logger.info("Self-test passed successfully!")

if __name__ == "__main__":
    _selftest()
