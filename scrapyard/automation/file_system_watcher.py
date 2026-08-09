"""
file_system_watcher — Monitor file system changes for real-time automation. Provides a robust, cross-platform watcher with filtering and event handling.

### PART-META-JSON
{
  "name": "file_system_watcher",
  "layer": "automation",
  "purpose": "Monitor file system changes for real-time automation. Provides a robust, cross-platform watcher with filtering and event handling.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: FileWatcher(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.automation.file_system_watcher`.",
  "example": "from scrapyard.automation.file_system_watcher import *",
  "import_path": "scrapyard.automation.file_system_watcher"
}
### END-PART-META
"""

import os
import re
import time
import fnmatch
import logging
from typing import Callable

logger = logging.getLogger(__name__)

class FileWatcher:
    def __init__(self, root: str, *, recursive: bool = True, case_sensitive: bool = False):
        self.root = root
        self.recursive = recursive
        self.case_sensitive = case_sensitive
        self.filters = []
        self.callbacks = {}
        self.running = False

    def start(self) -> None:
        if self.running:
            raise RuntimeError("File watcher is already running")
        self.running = True
        logger.info(f"Starting file watcher on {self.root} (recursive={self.recursive})")

    def stop(self) -> None:
        if not self.running:
            raise RuntimeError("File watcher is not running")
        self.running = False
        logger.info("Stopping file watcher")

    def add_filter(self, pattern: str) -> None:
        if not re.match(r'^[a-zA-Z0-9\*\?\[\]\.\-\|]+$', pattern):
            raise ValueError("Invalid filter pattern")
        self.filters.append(pattern)

    def on_event(self, callback: Callable[[str, str], None]) -> None:
        self.callbacks['event'] = callback

    def _match_pattern(self, path: str) -> bool:
        # No filters => match everything. Filters are glob patterns (e.g. "*.txt")
        # matched against the file's basename; a path matches if ANY filter matches.
        if not self.filters:
            return True
        name = os.path.basename(path)
        subject = name if self.case_sensitive else name.lower()
        for pattern in self.filters:
            pat = pattern if self.case_sensitive else pattern.lower()
            if fnmatch.fnmatchcase(subject, pat):
                return True
        return False

    def _watch_directory(self, directory: str) -> None:
        for entry in os.scandir(directory):
            if entry.is_file():
                if self._match_pattern(entry.path):
                    logger.debug(f"File {entry.path} matches filter")
                    self.callbacks['event'](entry.path, 'modify')
            elif entry.is_dir() and self.recursive:
                self._watch_directory(entry.path)

    def _throttle(self) -> None:
        time.sleep(0.1)  # Throttle to avoid overwhelming the system

    def run(self) -> None:
        if not self.running:
            raise RuntimeError("File watcher is not started")
        for entry in os.scandir(self.root):
            if entry.is_file():
                if self._match_pattern(entry.path):
                    logger.debug(f"File {entry.path} matches filter")
                    self.callbacks['event'](entry.path, 'modify')
            elif entry.is_dir() and self.recursive:
                self._watch_directory(entry.path)
        while self.running:
            for event in os.scandir(self.root):
                if event.is_file():
                    if self._match_pattern(event.path):
                        logger.debug(f"Event detected on file {event.path}")
                        self.callbacks['event'](event.path, 'modify')
                        self._throttle()
                elif event.is_dir() and self.recursive:
                    self._watch_directory(event.path)
            time.sleep(0.1)  # Polling interval

def _selftest():
    import tempfile
    import threading

    events = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
        # Pre-create one matching and one non-matching file.
        txt = os.path.join(tempdir, "note.txt")
        log = os.path.join(tempdir, "debug.log")
        with open(txt, "w") as f:
            f.write("hi")
        with open(log, "w") as f:
            f.write("nope")

        watcher = FileWatcher(tempdir, recursive=True)
        watcher.add_filter("*.txt")
        watcher.on_event(lambda p, ev: events.append((os.path.basename(p), ev)))
        watcher.start()

        th = threading.Thread(target=watcher.run, daemon=True)
        th.start()
        time.sleep(0.35)  # a few poll cycles
        # Create a second matching file while the watcher runs.
        with open(os.path.join(tempdir, "second.txt"), "w") as f:
            f.write("x")
        time.sleep(0.35)
        watcher.stop()
        th.join(timeout=2)

    names = {n for n, _ in events}
    # Matching files are reported.
    assert "note.txt" in names, names
    assert "second.txt" in names, names
    # NEGATIVE: a non-matching file is never reported.
    assert "debug.log" not in names, names
    # Every reported event carries an event type.
    assert events and all(ev == "modify" for _, ev in events)

    # NEGATIVE: an invalid filter pattern is rejected.
    try:
        FileWatcher(tempdir).add_filter("bad;pattern")
        raise AssertionError("invalid filter pattern accepted")
    except ValueError:
        pass

    print("file_system_watcher selftest OK")


if __name__ == "__main__":
    _selftest()
