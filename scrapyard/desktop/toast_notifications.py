"""
toast_notifications — Display real desktop toast notifications (Windows via PowerShell/WinRT, Linux via notify-send, macOS via osascript) with a logged dry-run fallback for headless environments.

### PART-META-JSON
{
  "name": "toast_notifications",
  "layer": "desktop",
  "purpose": "Show OS toast notifications: Windows via PowerShell WinRT ToastNotificationManager, Linux via notify-send, macOS via osascript; headless/dry-run mode records the toast instead of displaying it.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "title, message, optional duration hint and urgency; dry_run flag.",
  "outputs": "OS notification displayed (returns backend used), or 'dryrun' record in LAST_TOAST.",
  "files_created": [],
  "security_notes": "Title/message are passed to the OS shell tool as argv (never interpolated into a shell string) and XML-escaped for the Windows toast payload, so notification text cannot inject commands. Do not put secrets in toasts; they persist in the OS notification center.",
  "ai_usage": "show_toast(title, message) fire-and-forget; ToastNotification(...).show() for the object form. Pass dry_run=True in tests/CI.",
  "example": "from scrapyard.desktop.toast_notifications import show_toast; show_toast('Build done', 'All 42 tests green')",
  "import_path": "scrapyard.desktop.toast_notifications"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from typing import Optional
from xml.sax.saxutils import escape

STATUS = "core"

logger = logging.getLogger(__name__)

# Last toast issued (backend, title, message) — inspectable by tests/callers.
LAST_TOAST: Optional[dict] = None

_PS_TOAST_TEMPLATE = """
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($args[0])
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($args[1]).Show($toast)
"""


def _windows_toast(title: str, message: str, app_id: str) -> bool:
    """Show a native Windows toast through PowerShell + WinRT. Returns success."""
    xml = (f"<toast><visual><binding template='ToastGeneric'>"
           f"<text>{escape(title)}</text><text>{escape(message)}</text>"
           f"</binding></visual></toast>")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             _PS_TOAST_TEMPLATE, xml, app_id],
            capture_output=True, timeout=15)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.debug("Windows toast failed: %s", e)
        return False


def _linux_toast(title: str, message: str, urgency: int) -> bool:
    if shutil.which("notify-send") is None:
        return False
    level = {0: "low", 1: "normal", 2: "critical"}.get(urgency, "normal")
    try:
        proc = subprocess.run(["notify-send", "-u", level, title, message],
                              capture_output=True, timeout=10)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _macos_toast(title: str, message: str) -> bool:
    if shutil.which("osascript") is None:
        return False
    script = f'display notification "{message.replace(chr(34), chr(39))}" with title "{title.replace(chr(34), chr(39))}"'
    try:
        proc = subprocess.run(["osascript", "-e", script],
                              capture_output=True, timeout=10)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def show_toast(title: str, message: str, icon: Optional[str] = None,
               duration: int = 5, urgency: int = 1, dry_run: bool = False,
               app_id: str = "scrapyard.desktop") -> str:
    """Display a toast notification. Returns the backend used:
    'windows' | 'linux' | 'macos' | 'log' (headless fallback) | 'dryrun'.

    Never raises on display failure — falls back to logging so callers'
    workflows are not broken by notification plumbing.
    """
    global LAST_TOAST
    if not title and not message:
        raise ValueError("toast needs a title or a message")

    backend = "dryrun"
    if not dry_run:
        system = platform.system()
        shown = False
        if system == "Windows":
            shown = _windows_toast(title, message, app_id)
            backend = "windows"
        elif system == "Linux":
            shown = _linux_toast(title, message, urgency)
            backend = "linux"
        elif system == "Darwin":
            shown = _macos_toast(title, message)
            backend = "macos"
        if not shown:
            backend = "log"
            logger.info("TOAST (fallback): %s - %s", title, message)

    LAST_TOAST = {"backend": backend, "title": title, "message": message,
                  "icon": icon, "duration": duration, "urgency": urgency}
    return backend


class ToastNotification:
    """Object form of show_toast for callers that build the toast up front."""

    def __init__(self, title: str, message: str, icon: Optional[str] = None,
                 duration: int = 5, urgency: int = 1):
        self.title = title
        self.message = message
        self.icon = icon
        self.duration = duration
        self.urgency = urgency

    def show(self, dry_run: bool = False) -> str:
        return show_toast(self.title, self.message, icon=self.icon,
                          duration=self.duration, urgency=self.urgency,
                          dry_run=dry_run)


def _selftest() -> None:
    """Headless-safe: exercises the API in dry-run mode (no OS UI required),
    validates argument handling and the XML escaping used for Windows."""
    import time
    start = time.time()

    backend = show_toast("Test Title", "This is a test message.", duration=2, dry_run=True)
    assert backend == "dryrun"
    assert LAST_TOAST is not None and LAST_TOAST["title"] == "Test Title"

    toast = ToastNotification(title="Custom <Title>", message='Msg & "quotes"',
                              icon="star", duration=3, urgency=2)
    assert toast.show(dry_run=True) == "dryrun"
    assert LAST_TOAST["message"] == 'Msg & "quotes"'

    # XML escaping must neutralize markup-significant characters.
    escaped = escape('<script>&"')
    assert "<" not in escaped.replace("&lt;", "") and "&\"" not in escaped

    # Empty toast must be rejected.
    try:
        show_toast("", "", dry_run=True)
    except ValueError:
        pass
    else:
        raise AssertionError("empty toast must raise ValueError")

    # A real display attempt must not raise even if no notifier is available;
    # it reports which backend handled it.
    real_backend = show_toast("scrapyard selftest", "toast_notifications OK")
    assert real_backend in ("windows", "linux", "macos", "log")

    assert time.time() - start < 20, "selftest exceeded 20s budget"
    logger.info("toast_notifications selftest passed (real backend: %s)", real_backend)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
