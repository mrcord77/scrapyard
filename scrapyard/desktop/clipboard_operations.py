"""
clipboard_operations — Get/set system clipboard text: real Win32 clipboard via ctypes on Windows, pyperclip elsewhere if installed, thread-safe in-process buffer as the headless fallback.

### PART-META-JSON
{
  "name": "clipboard_operations",
  "layer": "desktop",
  "purpose": "System clipboard text get/set. Windows: native Win32 API via ctypes (CF_UNICODETEXT, no third-party deps). Other platforms: pyperclip when available. Headless fallback: thread-safe in-process buffer, reported via active_backend().",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Text to copy (str).",
  "outputs": "Clipboard text (str, empty when clipboard is empty/non-text); active_backend() name.",
  "files_created": [],
  "security_notes": "The clipboard is shared with every app the user runs: never place secrets on it without an explicit user action, and treat pasted content as untrusted input. The in-process fallback buffer is process-local and never leaves memory.",
  "ai_usage": "get_clipboard_text()/set_clipboard_text(); check active_backend() if you must know whether a real OS clipboard is in play.",
  "example": "from scrapyard.desktop.clipboard_operations import set_clipboard_text, get_clipboard_text; set_clipboard_text('hi'); assert get_clipboard_text() == 'hi'",
  "import_path": "scrapyard.desktop.clipboard_operations"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import sys
import threading

STATUS = "core"

logger = logging.getLogger(__name__)

_fallback_lock = threading.Lock()
_fallback_buffer = ""

_pyperclip_module = None
_pyperclip_checked = False


class ClipboardOperationError(Exception):
    """Raised when a real clipboard backend fails mid-operation."""


# ------------------------------------------------------ Win32 ctypes backend ---

def _win32_get() -> str:
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    if not user32.OpenClipboard(None):
        raise ClipboardOperationError("OpenClipboard failed")
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""  # empty or non-text clipboard
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            raise ClipboardOperationError("GlobalLock failed")
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _win32_set(text: str) -> None:
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]

    data = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        raise ClipboardOperationError("OpenClipboard failed")
    try:
        if not user32.EmptyClipboard():
            raise ClipboardOperationError("EmptyClipboard failed")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise ClipboardOperationError("GlobalAlloc failed")
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            raise ClipboardOperationError("GlobalLock failed")
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise ClipboardOperationError("SetClipboardData failed")
        # Ownership of the handle passed to the OS on success — do not free.
    finally:
        user32.CloseClipboard()


# --------------------------------------------------------- backend selection ---

def _get_pyperclip():
    global _pyperclip_module, _pyperclip_checked
    if not _pyperclip_checked:
        _pyperclip_checked = True
        try:
            import pyperclip
            pyperclip.paste()  # probe: fails on headless setups
            _pyperclip_module = pyperclip
        except Exception as e:  # noqa: BLE001 — any failure means "unavailable"
            logger.debug("pyperclip unavailable: %s", e)
    return _pyperclip_module


def active_backend() -> str:
    """'win32' | 'pyperclip' | 'buffer' — which clipboard this process is using."""
    if sys.platform == "win32":
        try:
            _win32_get()
            return "win32"
        except Exception:  # noqa: BLE001 — e.g. clipboard locked by another app
            pass
    if _get_pyperclip() is not None:
        return "pyperclip"
    return "buffer"


def get_clipboard_text() -> str:
    """Return clipboard text ('' when empty or non-text)."""
    if sys.platform == "win32":
        try:
            return _win32_get()
        except ClipboardOperationError as e:
            logger.debug("win32 clipboard read failed (%s); trying fallback", e)
    pyperclip = _get_pyperclip()
    if pyperclip is not None:
        result = pyperclip.paste()
        return result if result is not None else ""
    with _fallback_lock:
        return _fallback_buffer


def set_clipboard_text(text: str) -> None:
    """Copy *text* to the clipboard."""
    if not isinstance(text, str):
        raise TypeError("clipboard text must be str")
    global _fallback_buffer
    if sys.platform == "win32":
        try:
            _win32_set(text)
            return
        except ClipboardOperationError as e:
            logger.debug("win32 clipboard write failed (%s); trying fallback", e)
    pyperclip = _get_pyperclip()
    if pyperclip is not None:
        pyperclip.copy(text)
        return
    with _fallback_lock:
        _fallback_buffer = text


def _selftest() -> None:
    """Round-trips text through the active backend (real OS clipboard on
    Windows), restoring the user's original clipboard afterwards."""
    original = None
    try:
        original = get_clipboard_text()
    except Exception as e:  # noqa: BLE001
        logger.warning("could not snapshot original clipboard: %s", e)

    try:
        set_clipboard_text("")
        assert get_clipboard_text() == "", "empty clipboard round-trip failed"

        test_text = "Scrapyard Clipboard Test 12345"
        set_clipboard_text(test_text)
        assert get_clipboard_text() == test_text, "ascii round-trip failed"

        unicode_text = "Unicode Test: 你好世界 \U0001f680 émojis"
        set_clipboard_text(unicode_text)
        assert get_clipboard_text() == unicode_text, "unicode round-trip failed"

        try:
            set_clipboard_text(123)  # type: ignore[arg-type]
        except TypeError:
            pass
        else:
            raise AssertionError("non-str must raise TypeError")

        logger.info("clipboard selftest passed (backend: %s)", active_backend())
    finally:
        if original is not None:
            try:
                set_clipboard_text(original)
            except Exception as e:  # noqa: BLE001
                logger.warning("could not restore original clipboard: %s", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
