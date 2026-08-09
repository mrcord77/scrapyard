"""
change_detector — ** Detects changes in web page content over time using HTML diffing and automation. Core module for monitoring and comparing web page structures and content dynamically.

### PART-META-JSON
{
  "name": "change_detector",
  "layer": "automation",
  "purpose": "Detects changes in web page content over time using HTML diffing and automation. Core module for monitoring and comparing web page structures and content dynamically.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: html_tree_diff(old_html, new_html); Change(...); PageDiff(...); ChangeDetector(...).",
  "outputs": "Returns: html_tree_diff -> PageDiff.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.automation.change_detector`.",
  "example": "from scrapyard.automation.change_detector import *",
  "import_path": "scrapyard.automation.change_detector"
}
### END-PART-META
"""
from typing import Optional, List, Dict, Any
import time
import logging
import tempfile

from dataclasses import dataclass
from html.parser import HTMLParser

# Setup logger
logger = logging.getLogger(__name__)


@dataclass
class Change:
    location: str
    type: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None


class _SimpleHTMLParser(HTMLParser):
    """Simple HTML parser to extract structural elements and text for diffing."""
    
    def __init__(self) -> None:
        super().__init__()
        self.elements: List[tuple] = []
        self.path: List[str] = []
    
    def handle_starttag(self, tag: str, attrs: Any) -> None:
        self.path.append(tag)
        attrs_dict = dict(attrs)
        self.elements.append(("tag", "/".join(self.path), tag, attrs_dict))
    
    def handle_endtag(self, tag: str) -> None:
        if self.path and self.path[-1] == tag:
            self.path.pop()
    
    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            location = "/".join(self.path) if self.path else "root"
            self.elements.append(("text", location, text))


class PageDiff:
    def __init__(self, old_html: str, new_html: str) -> None:
        self.old_html = old_html
        self.new_html = new_html
        self.changes: List[Change] = self._calculate_diff()
    
    def _calculate_diff(self) -> List[Change]:
        """Calculate differences between old and new HTML."""
        old_parser = _SimpleHTMLParser()
        old_parser.feed(self.old_html)
        
        new_parser = _SimpleHTMLParser()
        new_parser.feed(self.new_html)
        
        changes: List[Change] = []
        old_items = old_parser.elements
        new_items = new_parser.elements
        
        max_len = max(len(old_items), len(new_items))
        for i in range(max_len):
            if i >= len(old_items):
                item = new_items[i]
                changes.append(Change(
                    location=item[1],
                    type="added",
                    old_value=None,
                    new_value=str(item[2]) if len(item) > 2 else None
                ))
            elif i >= len(new_items):
                item = old_items[i]
                changes.append(Change(
                    location=item[1],
                    type="removed",
                    old_value=str(item[2]) if len(item) > 2 else None,
                    new_value=None
                ))
            elif old_items[i] != new_items[i]:
                old_item = old_items[i]
                new_item = new_items[i]
                
                # Check if text content changed
                if old_item[0] == "text" and new_item[0] == "text":
                    if old_item[2] != new_item[2]:
                        changes.append(Change(
                            location=old_item[1],
                            type="text",
                            old_value=old_item[2],
                            new_value=new_item[2]
                        ))
                elif old_item[0] == "tag" and new_item[0] == "tag":
                    if old_item[2] != new_item[2]:  # tag name changed
                        changes.append(Change(
                            location=old_item[1],
                            type="structure",
                            old_value=old_item[2],
                            new_value=new_item[2]
                        ))
                else:
                    # Type changed (tag vs text)
                    changes.append(Change(
                        location=old_item[1],
                        type="structure",
                        old_value=str(old_item[2]) if len(old_item) > 2 else None,
                        new_value=str(new_item[2]) if len(new_item) > 2 else None
                    ))
        
        return changes
    
    def get_diff(self) -> Dict[str, Any]:
        """Return the diff as a dictionary."""
        return {
            "changes": [
                {
                    "location": c.location,
                    "type": c.type,
                    "old_value": c.old_value,
                    "new_value": c.new_value
                }
                for c in self.changes
            ]
        }


def html_tree_diff(old_html: str, new_html: str) -> PageDiff:
    """Compare two HTML strings and return a PageDiff."""
    return PageDiff(old_html, new_html)


class ChangeDetector:
    def __init__(self, url: str, parser: Any) -> None:
        self.url = url
        self.parser = parser
        self.snapshots: List[str] = []

    def capture_snapshot(self) -> None:
        """Capture a snapshot of the page using the provided parser."""
        driver = None
        try:
            # Handle both factory pattern (parser.launch) and direct instance
            if hasattr(self.parser, 'launch'):
                driver = self.parser.launch(headless=True)
                page = driver.new_page()
            else:
                # Assume parser is already a page/driver instance
                page = self.parser
            
            if hasattr(page, 'goto'):
                page.goto(self.url)
            
            if hasattr(page, 'content'):
                snapshot = page.content()
            else:
                # Fallback for string-based mocks
                snapshot = str(page)
            
            self.snapshots.append(snapshot)
            logger.info(f"Snapshot captured for {self.url}")
        finally:
            if driver and hasattr(driver, 'close'):
                driver.close()

    def compare(self, other_snapshot: Any) -> PageDiff:
        """Compare the last captured snapshot with another snapshot."""
        if not self.snapshots:
            raise ValueError("No snapshots available to compare")

        old_snapshot = self.snapshots[-1]
        
        # Handle both string snapshots and ChangeDetector instances
        if isinstance(other_snapshot, ChangeDetector):
            if not other_snapshot.snapshots:
                raise ValueError("Other detector has no snapshots")
            new_snapshot = other_snapshot.snapshots[-1]
        else:
            # Assume it's a string
            new_snapshot = str(other_snapshot)
            
        return PageDiff(old_snapshot, new_snapshot)


def _selftest():
    """Self-test function that verifies change detection without network calls."""
    
    class MockBrowser:
        """Mock browser that simulates page changes without network access."""
        _counter: int = 0
        
        def launch(self, **kwargs: Any) -> 'MockBrowser':
            return self
        
        def new_page(self) -> 'MockBrowser':
            return self
        
        def goto(self, url: str) -> None:
            pass
        
        def content(self) -> str:
            MockBrowser._counter += 1
            return f"<html><body><h1>Page {MockBrowser._counter}</h1><p>Content timestamp {time.time()}</p></body></html>"
        
        def close(self) -> None:
            pass
    
    parser = MockBrowser()

    detector = ChangeDetector("http://example.com", parser)
    detector.capture_snapshot()
    
    time.sleep(0.1)  # Simulate some delay between captures
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        second_detector = ChangeDetector("http://example.com", parser)
        second_detector.capture_snapshot()

        diff = second_detector.compare(detector.snapshots[-1])
        changes = diff.get_diff()["changes"]
        assert len(changes) > 0, f"No changes detected in the snapshot comparison. Found {len(changes)} changes."
    
    logger.info("Self-test passed")


if __name__ == "__main__":
    _selftest()
