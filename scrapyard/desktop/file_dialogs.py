"""
file_dialogs — Native open/save/directory selection dialogs via tkinter with parsed file-type filters and a headless-safe test seam.

### PART-META-JSON
{
  "name": "file_dialogs",
  "layer": "desktop",
  "purpose": "Open-file, save-file, and choose-directory dialogs via tkinter.filedialog, with 'Label (*.ext)' filter parsing; dialog functions are injectable so headless tests never open UI.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "title, initial_dir, filters like ['Text Files (*.txt)', 'All Files (*.*)'].",
  "outputs": "Selected absolute path string, or None if the user cancelled.",
  "files_created": [],
  "security_notes": "Returns whatever path the user picks - callers must validate it against their allowed roots before reading/writing (a dialog is not an authorization boundary). No shell involvement; tkinter only.",
  "ai_usage": "open_file_dialog/save_file_dialog/DirectoryDialog for interactive apps; pass _dialog_fn in tests to avoid real UI.",
  "example": "from scrapyard.desktop.file_dialogs import open_file_dialog; p = open_file_dialog('Pick a log', '.', ['Log Files (*.log)'])",
  "import_path": "scrapyard.desktop.file_dialogs"
}
### END-PART-META
"""
from __future__ import annotations

import re
from typing import Callable, List, Optional, Tuple

STATUS = "core"

_FILTER_RE = re.compile(r"^\s*(?P<label>[^(]+?)\s*\((?P<patterns>[^)]+)\)\s*$")


def parse_filters(filters: List[str]) -> List[Tuple[str, str]]:
    """Turn ['Text Files (*.txt)', 'All Files (*.*)'] into tkinter filetypes
    [('Text Files', '*.txt'), ('All Files', '*.*')]. Filters without a
    parenthesised pattern become ('<filter>', '*.*')."""
    parsed: List[Tuple[str, str]] = []
    for f in filters or []:
        m = _FILTER_RE.match(f)
        if m:
            patterns = " ".join(p.strip() for p in m.group("patterns").split(";"))
            parsed.append((m.group("label"), patterns))
        else:
            parsed.append((f.strip() or "All Files", "*.*"))
    return parsed or [("All Files", "*.*")]


def _run_dialog(dialog_fn: Callable, *, root_factory: Optional[Callable] = None,
                **kwargs) -> Optional[str]:
    """Create a hidden Tk root, run one dialog, destroy the root.
    Returns None when the user cancels (tkinter returns '' or ())."""
    if root_factory is None:
        import tkinter as tk
        root_factory = tk.Tk
    root = root_factory()
    root.withdraw()
    root.attributes("-topmost", True)  # dialog must not open behind other windows
    try:
        result = dialog_fn(parent=root, **kwargs)
    finally:
        root.destroy()
    return result if isinstance(result, str) and result else None


def open_file_dialog(title: str, initial_dir: str, filters: List[str],
                     _dialog_fn: Optional[Callable] = None,
                     _root_factory: Optional[Callable] = None) -> Optional[str]:
    """Show an open-file dialog; returns the chosen path or None on cancel.
    `_dialog_fn` overrides the tkinter dialog (test seam / custom backend)."""
    if _dialog_fn is None:
        from tkinter import filedialog
        _dialog_fn = filedialog.askopenfilename
    return _run_dialog(_dialog_fn, root_factory=_root_factory,
                       title=title, initialdir=initial_dir,
                       filetypes=parse_filters(filters))


def save_file_dialog(title: str, initial_dir: str, filters: List[str],
                     _dialog_fn: Optional[Callable] = None,
                     _root_factory: Optional[Callable] = None) -> Optional[str]:
    """Show a save-file dialog; returns the chosen path or None on cancel."""
    if _dialog_fn is None:
        from tkinter import filedialog
        _dialog_fn = filedialog.asksaveasfilename
    return _run_dialog(_dialog_fn, root_factory=_root_factory,
                       title=title, initialdir=initial_dir,
                       filetypes=parse_filters(filters))


class DirectoryDialog:
    """Choose-directory dialog. `show()` returns the path or None on cancel."""

    def __init__(self, title: str, initial_dir: str,
                 _dialog_fn: Optional[Callable] = None,
                 _root_factory: Optional[Callable] = None):
        self.title = title
        self.initial_dir = initial_dir
        self._dialog_fn = _dialog_fn
        self._root_factory = _root_factory

    def show(self) -> Optional[str]:
        fn = self._dialog_fn
        if fn is None:
            from tkinter import filedialog
            fn = filedialog.askdirectory
        return _run_dialog(fn, root_factory=self._root_factory,
                           title=self.title, initialdir=self.initial_dir)


def _selftest():
    """Headless: verifies filter parsing and the full dialog plumbing using an
    injected dialog function — no real UI is opened, so this cannot hang."""
    import os
    import tempfile

    # Filter parsing
    assert parse_filters(["Text Files (*.txt)"]) == [("Text Files", "*.txt")]
    assert parse_filters(["Images (*.png; *.jpg)"]) == [("Images", "*.png *.jpg")]
    assert parse_filters(["All Files (*.*)", "weird"]) == [("All Files", "*.*"), ("weird", "*.*")]
    assert parse_filters([]) == [("All Files", "*.*")]

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        chosen = os.path.join(temp_dir, "picked.txt")
        seen_kwargs = {}

        def fake_dialog(parent=None, **kwargs):
            # tkinter passes back '' on cancel; we emulate a selection and
            # record kwargs to prove title/initialdir/filetypes are wired.
            seen_kwargs.update(kwargs)
            assert parent is not None, "dialog must get a hidden Tk parent"
            return chosen

        def fake_cancel(parent=None, **kwargs):
            return ""

        class FakeRoot:
            def withdraw(self): pass
            def attributes(self, *_): pass
            def destroy(self): pass

        root_factory = FakeRoot

        # open
        p = open_file_dialog("Open It", temp_dir, ["Text Files (*.txt)"],
                             _dialog_fn=fake_dialog, _root_factory=root_factory)
        assert p == chosen
        assert seen_kwargs["title"] == "Open It"
        assert seen_kwargs["initialdir"] == temp_dir
        assert seen_kwargs["filetypes"] == [("Text Files", "*.txt")]

        # save
        p = save_file_dialog("Save It", temp_dir, ["All Files (*.*)"],
                             _dialog_fn=fake_dialog, _root_factory=root_factory)
        assert p == chosen

        # directory
        d = DirectoryDialog("Pick Dir", temp_dir, _dialog_fn=fake_dialog,
                            _root_factory=root_factory).show()
        assert d == chosen

        # cancel paths return None
        assert open_file_dialog("x", temp_dir, [], _dialog_fn=fake_cancel,
                                _root_factory=root_factory) is None
        assert save_file_dialog("x", temp_dir, [], _dialog_fn=fake_cancel,
                                _root_factory=root_factory) is None
        assert DirectoryDialog("x", temp_dir, _dialog_fn=fake_cancel,
                               _root_factory=root_factory).show() is None


if __name__ == "__main__":
    _selftest()
