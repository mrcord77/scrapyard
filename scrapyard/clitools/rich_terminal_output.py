"""
rich_terminal_output — Dependency-free rich-style terminal output: tables, progress bars, and a threaded spinner.

### PART-META-JSON
{
  "name": "rich_terminal_output",
  "layer": "clitools",
  "purpose": "Terminal presentation without third-party deps: print_table/TableRenderer for aligned tables, show_progress_bar/ProgressIndicator for progress, Spinner for long operations (thread-based, stoppable).",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Row dicts + headers; totals/current for progress; description strings.",
  "outputs": "Formatted text on stdout; renderers also return strings for testing.",
  "files_created": [],
  "security_notes": "Writes caller-supplied strings straight to the terminal - do not print untrusted data containing ANSI escapes without sanitizing. No files, no network.",
  "ai_usage": "Import print_table/show_progress_bar/Spinner from `scrapyard.clitools.rich_terminal_output`.",
  "example": "from scrapyard.clitools.rich_terminal_output import print_table; print_table([{'a': 1}], ['a'])",
  "import_path": "scrapyard.clitools.rich_terminal_output"
}
### END-PART-META
"""
from typing import List, Dict, Any
import time
import logging
import threading
import io
import sys

# Module-level logger only; no side-effects at import time.
logger = logging.getLogger(__name__)

__all__ = ["print_table", "show_progress_bar", "Spinner", "_selftest"]


class TableRenderer:
    """Render a list of dictionaries as an ASCII table."""

    def __init__(self, headers: List[str], data: List[Dict[str, Any]]) -> None:
        self.headers = headers
        self.data = data

    def render(self) -> str:
        # Compute per-column widths from headers and row values.
        max_lengths = [len(str(header)) for header in self.headers]
        for row in self.data:
            for i, header in enumerate(self.headers):
                value = row.get(header)
                max_lengths[i] = max(max_lengths[i], len(str(value)))

        # Top/middle/bottom separator line.
        separator_line = "+" + "+".join("-" * (length + 2) for length in max_lengths) + "+"

        # Header row, padded to column width + 2.
        header_row = (
            "|"
            + " | ".join(
                f"{header:^{max_lengths[i] + 2}}" for i, header in enumerate(self.headers)
            )
            + "|"
        )

        # Data rows, padded to column width + 2.
        data_rows = []
        for row in self.data:
            cells = []
            for i, header in enumerate(self.headers):
                value = row.get(header)
                cells.append(f"{str(value).strip():^{max_lengths[i] + 2}}")
            data_rows.append("|" + " | ".join(cells) + "|")

        return "\n".join([separator_line, header_row, separator_line] + data_rows + [separator_line])


def print_table(data: List[Dict[str, Any]], headers: List[str]) -> None:
    """Print a formatted ASCII table from *data* using *headers*."""
    if not isinstance(data, list):
        raise TypeError("data must be a list of dicts")
    if not isinstance(headers, list):
        raise TypeError("headers must be a list")
    if not headers:
        raise ValueError("headers must not be empty")
    for row in data:
        if not isinstance(row, dict):
            raise TypeError("each row in data must be a dict")

    renderer = TableRenderer(headers=headers, data=data)
    print(renderer.render())


class ProgressIndicator:
    def __init__(self, total: int, description: str = ""):
        if not isinstance(total, int):
            raise TypeError("total must be an integer")
        if total <= 0:
            raise ValueError("total must be greater than 0")
        self.total = total
        self.current = 0
        self.description = description

    def update(self, current: int) -> None:
        if not isinstance(current, int):
            raise TypeError("current must be an integer")
        if not (0 <= current <= self.total):
            raise ValueError("current value must be between 0 and total")
        self.current = current

    def render(self) -> str:
        percent = (self.current / self.total) * 100
        bar_length = 50
        filled_length = int(bar_length * (self.current / self.total))
        bar = "█" * filled_length + "-" * (bar_length - filled_length)
        prefix = f"{self.description}: " if self.description else ""
        return f"{prefix}[{bar}] {percent:.2f}%"


def show_progress_bar(total: int, current: int, description: str = "") -> None:
    """Print a progress bar to the terminal."""
    indicator = ProgressIndicator(total=total, description=description)
    indicator.update(current=current)
    rendered = indicator.render()
    if current == total:
        print(rendered, flush=True)
    else:
        print(rendered, end="\r", flush=True)


class Spinner:
    """Non-blocking terminal spinner."""

    _frames = ["-", "\\", "|", "/"]
    _frame_delay = 0.1

    def __init__(self, description: str = ""):
        self.description = description
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._index = 0

    def _animate(self) -> None:
        while not self._stop_event.is_set():
            frame = self._frames[self._index % len(self._frames)]
            with self._lock:
                print(f"\r{self.description}: {frame}", end="", flush=True)
            self._index += 1
            time.sleep(self._frame_delay)

    def start(self) -> None:
        """Start the spinner animation in a background thread."""
        if self._running:
            raise RuntimeError("Spinner is already running")
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self, success: bool = True) -> None:
        """Stop the spinner and print a final status message."""
        if not self._running:
            # Nothing running; just print the final status.
            status = "Success!" if success else "Failed!"
            print(f"{self.description}: {status}")
            return

        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._running = False

        with self._lock:
            status = "Success!" if success else "Failed!"
            # Extra spaces clear any leftover spinner character.
            print(f"\r{self.description}: {status}   ", flush=True)


def _selftest() -> None:
    import sqlite3
    import tempfile
    import os

    passed_checks = 0

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "rich_terminal_output_selftest.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS results (id INTEGER PRIMARY KEY, test_name TEXT, passed INTEGER)"
            )

            # --- print_table tests ---
            data = [
                {"Name": "Part A", "Price": 10.5, "Quantity": 20},
                {"Name": "Part B", "Price": 20.75, "Quantity": 15},
            ]
            headers = ["Name", "Price", "Quantity"]

            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            try:
                print_table(data, headers)
                table_output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert "Name" in table_output
            assert "Price" in table_output
            assert "Quantity" in table_output
            assert "Part A" in table_output
            assert "Part B" in table_output
            assert "10.5" in table_output
            assert "20.75" in table_output
            passed_checks += 1
            conn.execute(
                "INSERT INTO results (test_name, passed) VALUES (?, ?)",
                ("print_table_rendering", 1),
            )

            # Empty data should still render headers.
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            try:
                print_table([], ["Name"])
                empty_output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout
            assert "Name" in empty_output
            passed_checks += 1

            # Invalid table inputs.
            try:
                print_table("not a list", headers)
                raise AssertionError("expected TypeError for non-list data")
            except TypeError:
                passed_checks += 1

            try:
                print_table(data, [])
                raise AssertionError("expected ValueError for empty headers")
            except ValueError:
                passed_checks += 1

            try:
                print_table(["not a dict"], headers)
                raise AssertionError("expected TypeError for non-dict row")
            except TypeError:
                passed_checks += 1

            # --- show_progress_bar tests ---
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            try:
                show_progress_bar(total=100, current=50, description="Progress")
                progress_output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout
            assert "50.00%" in progress_output
            passed_checks += 1
            conn.execute(
                "INSERT INTO results (test_name, passed) VALUES (?, ?)",
                ("show_progress_bar_rendering", 1),
            )

            # Completion should end with a newline.
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            try:
                show_progress_bar(total=10, current=10)
                complete_output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout
            assert "100.00%" in complete_output
            passed_checks += 1

            # Invalid progress inputs.
            try:
                show_progress_bar(total=0, current=0)
                raise AssertionError("expected ValueError for non-positive total")
            except ValueError:
                passed_checks += 1

            try:
                show_progress_bar(total=100, current=-1)
                raise AssertionError("expected ValueError for negative current")
            except ValueError:
                passed_checks += 1

            try:
                show_progress_bar(total=100, current=101)
                raise AssertionError("expected ValueError for current > total")
            except ValueError:
                passed_checks += 1

            # --- Spinner tests ---
            spinner = Spinner("Loading")
            spinner.start()
            time.sleep(0.3)
            spinner.stop(success=True)
            passed_checks += 1
            conn.execute(
                "INSERT INTO results (test_name, passed) VALUES (?, ?)",
                ("spinner_start_stop", 1),
            )

            spinner2 = Spinner("Failing")
            spinner2.start()
            time.sleep(0.2)
            spinner2.stop(success=False)
            passed_checks += 1

            # Restart after stop.
            spinner.start()
            time.sleep(0.2)
            spinner.stop(success=True)
            passed_checks += 1

            # Double-start should raise.
            spinner3 = Spinner("Double")
            spinner3.start()
            try:
                spinner3.start()
                raise AssertionError("expected RuntimeError for double start")
            except RuntimeError:
                passed_checks += 1
            finally:
                spinner3.stop(success=True)

            # Verify SQLite persistence worked.
            cursor = conn.execute("SELECT COUNT(*) FROM results WHERE passed = 1")
            sqlite_count = cursor.fetchone()[0]
            assert sqlite_count >= 3
            passed_checks += 1

            logger.info("rich_terminal_output _selftest passed %d checks", passed_checks)
        finally:
            conn.close()

    print(f"_selftest passed ({passed_checks} checks)")


if __name__ == "__main__":
    _selftest()
