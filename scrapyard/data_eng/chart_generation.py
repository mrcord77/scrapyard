"""
chart_generation — ** Generates customizable visualizations for data analysis workflows. Provides reusable, high-level charting functions that abstract matplotlib complexity while enabling fine-grained control.

### PART-META-JSON
{
  "name": "chart_generation",
  "layer": "data_eng",
  "domain": "data_analysis",
  "purpose": "Generates customizable visualizations for data analysis workflows: line, bar, and scatter charts from pandas DataFrames with column validation, label/title/style kwargs, and tick auto-rotation - abstracting matplotlib boilerplate while returning the Figure for fine-grained control.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "pandas",
    "matplotlib"
  ],
  "inputs": "A pandas DataFrame plus x/y column names; optional kwargs (title, xlabel, ylabel, style, figsize, plus matplotlib pass-through kwargs).",
  "outputs": "matplotlib Figure objects (caller saves/renders them).",
  "files_created": [],
  "security_notes": "No network, subprocess, or secret handling. Column names and label/title kwargs are rendered into figure text - matplotlib treats $...$ as mathtext, so hostile column names can at worst distort rendering, not execute code. Figures returned are not closed by this module; long-running callers must plt.close() them to avoid memory growth. When rendering data derived from untrusted sources, review labels before publishing charts (data exfil via labels, not code risk).",
  "ai_usage": "plot_line_chart(df, 'x_col', 'y_col', title='...'), bar_chart(...), scatter_plot(...); use fig.savefig(path) on the returned Figure.",
  "example": "from scrapyard.data_eng.chart_generation import plot_line_chart",
  "import_path": "scrapyard.data_eng.chart_generation"
}
### END-PART-META
"""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Any, Tuple

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib.figure import Figure

logger = logging.getLogger(__name__)


def _validate_dataframe(df: Any, x: str, y: str) -> None:
    """Validate DataFrame and column existence."""
    import pandas as pd
    
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Expected pandas DataFrame, got {type(df).__name__}")
    
    if x not in df.columns:
        raise ValueError(f"Column '{x}' not found in DataFrame. Available columns: {list(df.columns)}")
    
    if y not in df.columns:
        raise ValueError(f"Column '{y}' not found in DataFrame. Available columns: {list(df.columns)}")


def _setup_figure(**kwargs: Any) -> Tuple[Any, Any]:
    """Create figure and axis with optional styling."""
    import matplotlib.pyplot as plt
    
    style = kwargs.get('style')
    figsize = kwargs.get('figsize', (10, 6))
    
    if style:
        with plt.style.context(style):
            fig, ax = plt.subplots(figsize=figsize)
    else:
        fig, ax = plt.subplots(figsize=figsize)
    
    return fig, ax


def _apply_labels(ax: Any, x: str, y: str, **kwargs: Any) -> None:
    """Apply axis labels and title."""
    title = kwargs.get('title')
    if title:
        ax.set_title(title)
    ax.set_xlabel(kwargs.get('xlabel', x))
    ax.set_ylabel(kwargs.get('ylabel', y))


def plot_line_chart(df: pd.DataFrame, x: str, y: str, **kwargs: Any) -> Figure:
    """Generate a line chart from DataFrame."""
    import matplotlib.pyplot as plt
    
    _validate_dataframe(df, x, y)
    
    fig, ax = _setup_figure(**kwargs)
    
    # Filter out non-matplotlib kwargs
    plot_kwargs = {k: v for k, v in kwargs.items() 
                   if k not in ['style', 'figsize', 'title', 'xlabel', 'ylabel']}
    
    ax.plot(df[x], df[y], **plot_kwargs)
    _apply_labels(ax, x, y, **kwargs)
    
    # Auto-format x-axis for readability
    if len(df) > 5 or df[x].astype(str).str.len().max() > 10:
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    fig.tight_layout()
    return fig


def bar_chart(df: pd.DataFrame, x: str, y: str, **kwargs: Any) -> Figure:
    """Generate a bar chart from DataFrame."""
    import matplotlib.pyplot as plt
    
    _validate_dataframe(df, x, y)
    
    fig, ax = _setup_figure(**kwargs)
    
    plot_kwargs = {k: v for k, v in kwargs.items() 
                   if k not in ['style', 'figsize', 'title', 'xlabel', 'ylabel']}
    
    ax.bar(df[x], df[y], **plot_kwargs)
    _apply_labels(ax, x, y, **kwargs)
    
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    fig.tight_layout()
    return fig


def scatter_plot(df: pd.DataFrame, x: str, y: str, **kwargs: Any) -> Figure:
    """Generate a scatter plot from DataFrame."""
    
    _validate_dataframe(df, x, y)
    
    fig, ax = _setup_figure(**kwargs)
    
    plot_kwargs = {k: v for k, v in kwargs.items() 
                   if k not in ['style', 'figsize', 'title', 'xlabel', 'ylabel']}
    
    ax.scatter(df[x], df[y], **plot_kwargs)
    _apply_labels(ax, x, y, **kwargs)
    
    fig.tight_layout()
    return fig


def _selftest() -> None:
    """Module-level self-test."""
    import tempfile
    import sqlite3
    import os
    
    # Use non-interactive backend for testing
    import matplotlib
    matplotlib.use('Agg')
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        conn = sqlite3.connect(':memory:')
        try:
            cursor = conn.cursor()
            cursor.execute(
                'CREATE TABLE test_data (id INTEGER PRIMARY KEY, category TEXT, value REAL, score REAL)'
            )
            
            test_data = [
                (1, 'A', 10.5, 100.0),
                (2, 'B', 20.3, 150.0),
                (3, 'C', 15.8, 120.0),
                (4, 'D', 25.0, 200.0),
            ]
            cursor.executemany('INSERT INTO test_data VALUES (?, ?, ?, ?)', test_data)
            conn.commit()
            
            import pandas as pd
            import matplotlib.figure
            
            df = pd.read_sql_query('SELECT * FROM test_data', conn)
            
            # Test line chart renders without error
            fig1 = plot_line_chart(df, 'category', 'value')
            assert isinstance(fig1, matplotlib.figure.Figure)
            
            # Test bar chart renders without error
            fig2 = bar_chart(df, 'category', 'value', title='Test Bar Chart')
            assert isinstance(fig2, matplotlib.figure.Figure)
            
            # Test scatter plot renders without error
            fig3 = scatter_plot(df, 'value', 'score')
            assert isinstance(fig3, matplotlib.figure.Figure)
            
            # Test input validation rejects invalid column names
            try:
                plot_line_chart(df, 'nonexistent', 'value')
                assert False, "Expected ValueError for invalid x column"
            except ValueError as e:
                assert 'nonexistent' in str(e)
            
            try:
                bar_chart(df, 'category', 'nonexistent_y')
                assert False, "Expected ValueError for invalid y column"
            except ValueError as e:
                assert 'nonexistent_y' in str(e)
            
            # Test default theme is applied (no style specified)
            fig_default = plot_line_chart(df, 'category', 'value')
            assert fig_default is not None
            assert isinstance(fig_default, matplotlib.figure.Figure)
            
            # Verify output formats work (PNG, SVG)
            png_path = os.path.join(tmpdir, 'test.png')
            svg_path = os.path.join(tmpdir, 'test.svg')
            
            fig1.savefig(png_path, format='png')
            fig1.savefig(svg_path, format='svg')
            
            assert os.path.exists(png_path) and os.path.getsize(png_path) > 0
            assert os.path.exists(svg_path) and os.path.getsize(svg_path) > 0
            
        finally:
            conn.close()


if __name__ == "__main__":
    _selftest()
