"""
system_notification — Sends real desktop notifications on Windows (win10toast when
installed, PowerShell WinRT toast fallback) with honest capability reporting elsewhere.

### PART-META-JSON
{
  "name": "system_notification",
  "layer": "automation",
  "purpose": "Sends Windows desktop toast notifications through a clean interface: prefers the win10toast package when installed, otherwise falls back to a PowerShell Windows.UI.Notifications toast (no extra packages needed on Win10/11). is_notification_supported() reports capability; on unsupported platforms send_notification logs a warning and returns False instead of pretending success.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "win10toast (optional; PowerShell WinRT fallback used when absent)"
  ],
  "inputs": "Notification title and message strings; optional urgency (1-4, informational) and display duration.",
  "outputs": "A visible desktop toast; returns True when a dispatch path succeeded, False otherwise.",
  "files_created": [],
  "security_notes": "Title/message are rendered into the OS notification center and, on the PowerShell fallback, embedded into an XML toast payload - they are XML-escaped here to prevent markup injection, and the PowerShell script itself receives text only via an environment variable (never string-interpolated into the command), so notification text cannot inject PowerShell. Notifications are visible to anyone at the desktop: never put secrets, tokens, or sensitive PII in them. The fallback spawns powershell.exe with -NoProfile; no network access.",
  "ai_usage": "send_notification('Build done', 'All 76 parts green') on Windows; check is_notification_supported() first on shared code paths.",
  "example": "from scrapyard.automation.system_notification import send_notification",
  "import_path": "scrapyard.automation.system_notification"
}
### END-PART-META
"""

import logging
import os
import subprocess
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

# PowerShell fallback: reads title/message from environment variables so
# notification text can never inject into the script.
_PS_TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$title = $env:SCRAPYARD_TOAST_TITLE
$message = $env:SCRAPYARD_TOAST_MESSAGE
$template = @"
<toast><visual><binding template="ToastGeneric"><text>$title</text><text>$message</text></binding></visual></toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("scrapyard").Show($toast)
"""


def is_notification_supported() -> bool:
    """
    Check if system notifications are supported on the current platform.

    :return: True if notifications are supported, False otherwise
    """
    return os.name == 'nt'  # Currently supporting Windows


def _send_win10toast(title: str, message: str, duration: int) -> bool:
    try:
        from win10toast import ToastNotifier
    except ImportError:
        return False
    toaster = ToastNotifier()
    toaster.show_toast(title, message, duration=duration, threaded=True)
    return True


def _send_powershell_toast(title: str, message: str) -> bool:
    env = dict(os.environ)
    # XML-escape because the values are placed into a toast XML document.
    env["SCRAPYARD_TOAST_TITLE"] = escape(title)
    env["SCRAPYARD_TOAST_MESSAGE"] = escape(message)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             _PS_TOAST_SCRIPT],
            env=env, capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.error("PowerShell toast dispatch failed: %s", exc)
        return False
    if proc.returncode != 0:
        logger.error("PowerShell toast failed (exit %d): %s",
                     proc.returncode, (proc.stderr or "").strip()[:300])
        return False
    return True


def send_notification(title: str, message: str, urgency: int = 1,
                      duration: int = 5) -> bool:
    """
    Send a system notification with the given title and message.

    :param title: Title of the notification
    :param message: Message to be displayed in the notification
    :param urgency: Urgency level (1-4), informational only on Windows.
    :param duration: Display duration in seconds (win10toast path only).
    :return: True if a dispatch path succeeded, False otherwise.
    """
    if not title or not message:
        raise ValueError("title and message are required")
    if not 1 <= int(urgency) <= 4:
        raise ValueError("urgency must be between 1 and 4")
    if not is_notification_supported():
        logger.warning("Notifications are not supported on this platform (%s).",
                       os.name)
        return False

    if _send_win10toast(title, message, duration):
        return True
    logger.debug("win10toast unavailable; using PowerShell toast fallback")
    return _send_powershell_toast(title, message)


def _selftest():
    """Exercise dispatch selection without opening a real desktop notification."""
    # Input validation
    for bad in [("", "msg"), ("t", ""), ]:
        try:
            send_notification(*bad)
            raise AssertionError(f"should reject {bad}")
        except ValueError:
            pass
    try:
        send_notification("t", "m", urgency=9)
        raise AssertionError("should reject urgency 9")
    except ValueError:
        pass

    global is_notification_supported, _send_win10toast, _send_powershell_toast
    real_supported = is_notification_supported
    real_native = _send_win10toast
    real_fallback = _send_powershell_toast
    calls = []
    try:
        is_notification_supported = lambda: True
        _send_win10toast = lambda title, message, duration: False
        _send_powershell_toast = lambda title, message: calls.append((title, message)) or True
        assert send_notification("Build", "Done") is True
        assert calls == [("Build", "Done")]

        is_notification_supported = lambda: False
        assert send_notification("Build", "Done") is False
    finally:
        is_notification_supported = real_supported
        _send_win10toast = real_native
        _send_powershell_toast = real_fallback
    print("system_notification selftest: PASS (dispatch boundaries isolated)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
