"""
page_diff_reporter — Generates actionable reports and notifications for detected changes in web pages during automation tasks. It enables teams to track, review, and respond to UI or content drift in web applications.

### PART-META-JSON
{
  "name": "page_diff_reporter",
  "layer": "automation",
  "purpose": "Generates actionable reports and notifications for detected changes in web pages during automation tasks. It enables teams to track, review, and respond to UI or content drift in web applications.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "change_detector"
  ],
  "inputs": "Public API: ChangeNotification(...); Report(...); DiffReporter(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.automation.page_diff_reporter`.",
  "example": "from scrapyard.automation.page_diff_reporter import *",
  "import_path": "scrapyard.automation.page_diff_reporter"
}
### END-PART-META
"""

from typing import Optional, List, Dict, Any
import json

class ChangeNotification:
    def __init__(self, page_url: str, diff: str, severity: str):
        self.page_url = page_url
        self.diff = diff
        self.severity = severity
    
    def to_json(self) -> str:
        return json.dumps({
            "page_url": self.page_url,
            "diff": self.diff,
            "severity": self.severity
        })

class Report:
    def __init__(self, page_url: str, changes: List[ChangeNotification]):
        self.page_url = page_url
        self.changes = changes

class DiffReporter:
    def __init__(self, detector: Any, notifier: Any):
        self.detector = detector
        self.notifier = notifier
    
    def generate_report(self, old_snapshot: Dict[str, Any], new_snapshot: Dict[str, Any]) -> Report:
        changes = []
        for key in set(old_snapshot) | set(new_snapshot):
            if key not in old_snapshot or key not in new_snapshot:
                continue
            if old_snapshot[key] != new_snapshot[key]:
                diff = self._html_diff(key, old_snapshot[key], new_snapshot[key])
                if diff:
                    changes.append(ChangeNotification(key, diff, 'major' if diff else 'minor'))
        return Report(old_snapshot['url'], changes)
    
    def _html_diff(self, key: str, old_value: Any, new_value: Any) -> Optional[str]:
        # Simplified HTML diff logic
        if old_value == new_value:
            return None
        return f"Diff found in {key}: Old={old_value}, New={new_value}"

    def send_notification(self, report: Report):
        for change in report.changes:
            self.notifier.notify(change.to_json())

class Notifier:
    def notify(self, message: str):
        # Dummy implementation for notification
        print(f"Notification sent: {message}")

def _selftest():
    reporter = DiffReporter(object(), Notifier())

    old = {"url": "http://ex.com", "title": "Old", "content": "<p>A</p>"}
    new = {"url": "http://ex.com", "title": "New", "content": "<p>A</p>"}
    rep = reporter.generate_report(old, new)

    changed = {c.page_url for c in rep.changes}
    # Only the field that actually changed is reported.
    assert "title" in changed
    assert "content" not in changed  # identical value
    assert "url" not in changed      # identical value

    # The notification serializes to valid JSON carrying the diff detail.
    note = next(c for c in rep.changes if c.page_url == "title")
    d = json.loads(note.to_json())
    assert d["page_url"] == "title" and "Old" in d["diff"] and "New" in d["diff"]
    assert d["severity"] == "major"

    # NEGATIVE: identical snapshots produce no diff at all.
    same = reporter.generate_report(old, dict(old))
    assert same.changes == []

    # A key present on only one side is skipped, not reported as a change.
    rep2 = reporter.generate_report({"url": "u", "a": 1}, {"url": "u", "a": 1, "b": 2})
    assert all(c.page_url != "b" for c in rep2.changes)

    # send_notification runs without error against the dummy notifier.
    reporter.send_notification(rep)

    print("page_diff_reporter selftest OK")


if __name__ == "__main__":
    _selftest()
