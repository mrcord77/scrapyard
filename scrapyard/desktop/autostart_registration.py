"""
autostart_registration — Register/unregister an application for login autostart with a consistent API per OS (Windows HKCU Run key, macOS LaunchAgent, Linux XDG autostart), plus a dry-run mode.

### PART-META-JSON
{
  "name": "autostart_registration",
  "layer": "desktop",
  "purpose": "Register/unregister an application for login autostart: Windows HKCU Run registry value, macOS LaunchAgent plist, Linux XDG autostart .desktop entry. Dry-run mode plans without touching the system.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "app_name, command line to launch; dry_run flag.",
  "outputs": "Registry value / plist / .desktop entry created or removed; is_autostart_registered() bool.",
  "files_created": ["HKCU\\\\Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Run value (Windows)", "~/Library/LaunchAgents/<app>.plist (macOS)", "~/.config/autostart/<app>.desktop (Linux)"],
  "security_notes": "Writes only to per-user (HKCU / home-dir) autostart locations, never machine-wide. The registered command runs at every login: validate app_name/command come from the application itself, never from untrusted input. Use dry_run=True in tests/CI.",
  "ai_usage": "register_autostart(app_name, command), unregister_autostart(app_name), is_autostart_registered(app_name); pass dry_run=True to plan without side effects.",
  "example": "from scrapyard.desktop.autostart_registration import register_autostart; register_autostart('myapp', 'C:/apps/myapp.exe --minimized', dry_run=True)",
  "import_path": "scrapyard.desktop.autostart_registration"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import os
import platform
import plistlib
from typing import Dict, Optional

STATUS = "core"

logger = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def get_os_type() -> str:
    """Return 'Windows', 'macOS', 'Linux', or the raw platform.system() value."""
    system = platform.system()
    return {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(system, system)


def _validate(app_name: str, command: Optional[str] = None) -> None:
    if not app_name or not isinstance(app_name, str):
        raise ValueError("app_name must be a non-empty string")
    if command is not None and (not command or not isinstance(command, str)):
        raise ValueError("command must be a non-empty string")


# ------------------------------------------------------------------ Windows ---

def _win_register(app_name: str, command: str, dry_run: bool) -> Dict[str, str]:
    plan = {"action": "set", "key": f"HKCU\\{_RUN_KEY}", "value_name": app_name,
            "value": command}
    if dry_run:
        return plan
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, command)
    logger.info("Autostart registered for %r via HKCU Run key", app_name)
    return plan


def _win_unregister(app_name: str, dry_run: bool) -> Dict[str, str]:
    plan = {"action": "delete", "key": f"HKCU\\{_RUN_KEY}", "value_name": app_name}
    if dry_run:
        return plan
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, app_name)
        logger.info("Autostart unregistered for %r", app_name)
    except FileNotFoundError:
        logger.debug("No autostart Run value for %r to remove", app_name)
    return plan


def _win_is_registered(app_name: str) -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, app_name)
        return True
    except FileNotFoundError:
        return False


# -------------------------------------------------------------------- macOS ---

def _macos_plist_path(app_name: str) -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{app_name}.plist")


def _macos_register(app_name: str, command: str, dry_run: bool) -> Dict[str, str]:
    path = _macos_plist_path(app_name)
    plan = {"action": "write", "path": path, "value": command}
    if dry_run:
        return plan
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"Label": app_name, "ProgramArguments": command.split(), "RunAtLoad": True}
    with open(path, "wb") as f:
        plistlib.dump(payload, f)
    logger.info("Autostart LaunchAgent written for %r", app_name)
    return plan


def _macos_unregister(app_name: str, dry_run: bool) -> Dict[str, str]:
    path = _macos_plist_path(app_name)
    plan = {"action": "remove", "path": path}
    if not dry_run and os.path.exists(path):
        os.remove(path)
    return plan


# -------------------------------------------------------------------- Linux ---

def _linux_desktop_path(app_name: str) -> str:
    base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "autostart", f"{app_name}.desktop")


def _linux_register(app_name: str, command: str, dry_run: bool) -> Dict[str, str]:
    path = _linux_desktop_path(app_name)
    plan = {"action": "write", "path": path, "value": command}
    if dry_run:
        return plan
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"[Desktop Entry]\nType=Application\nName={app_name}\n"
                f"Exec={command}\nHidden=false\nX-GNOME-Autostart-enabled=true\n")
    logger.info("Autostart .desktop entry written for %r", app_name)
    return plan


def _linux_unregister(app_name: str, dry_run: bool) -> Dict[str, str]:
    path = _linux_desktop_path(app_name)
    plan = {"action": "remove", "path": path}
    if not dry_run and os.path.exists(path):
        os.remove(path)
    return plan


# ---------------------------------------------------------------- public API ---

def register_autostart(app_name: str, command: str, dry_run: bool = False) -> Dict[str, str]:
    """Register *command* to run at login for the current user.

    Returns the plan dict describing what was (or would be, with dry_run) done.
    """
    _validate(app_name, command)
    os_type = get_os_type()
    if os_type == "Windows":
        return _win_register(app_name, command, dry_run)
    if os_type == "macOS":
        return _macos_register(app_name, command, dry_run)
    if os_type == "Linux":
        return _linux_register(app_name, command, dry_run)
    raise OSError(f"Unsupported OS for autostart registration: {os_type}")


def unregister_autostart(app_name: str, dry_run: bool = False) -> Dict[str, str]:
    """Remove the login autostart entry for *app_name* (idempotent)."""
    _validate(app_name)
    os_type = get_os_type()
    if os_type == "Windows":
        return _win_unregister(app_name, dry_run)
    if os_type == "macOS":
        return _macos_unregister(app_name, dry_run)
    if os_type == "Linux":
        return _linux_unregister(app_name, dry_run)
    raise OSError(f"Unsupported OS for autostart registration: {os_type}")


def is_autostart_registered(app_name: str) -> bool:
    """True if an autostart entry currently exists for *app_name*."""
    _validate(app_name)
    os_type = get_os_type()
    if os_type == "Windows":
        return _win_is_registered(app_name)
    if os_type == "macOS":
        return os.path.exists(_macos_plist_path(app_name))
    if os_type == "Linux":
        return os.path.exists(_linux_desktop_path(app_name))
    return False


def _selftest() -> None:
    """Offline self-test: validate platform plans without changing login state."""
    import uuid

    app = f"scrapyard_autostart_selftest_{uuid.uuid4().hex[:8]}"
    cmd = "python -c \"pass\""

    # Dry-run every platform branch; none may touch registry or home files.
    global get_os_type
    real_get_os_type = get_os_type
    try:
        for os_type, expected in (("Windows", "set"), ("macOS", "write"),
                                  ("Linux", "write")):
            get_os_type = lambda value=os_type: value
            plan = register_autostart(app, cmd, dry_run=True)
            assert plan["action"] == expected, plan
            plan = unregister_autostart(app, dry_run=True)
            assert plan["action"] in ("delete", "remove"), plan
    finally:
        get_os_type = real_get_os_type

    # Validation
    for bad in ("", None):
        try:
            register_autostart(bad, cmd)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError("invalid app_name must raise")

    logger.info("autostart_registration selftest passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
