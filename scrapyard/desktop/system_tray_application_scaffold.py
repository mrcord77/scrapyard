"""
system_tray_application_scaffold — Reusable scaffold for tray-style background apps: menu model, stoppable event loop, hotkey registry, real toast delegation, and EOF-safe console forms.

### PART-META-JSON
{
  "name": "system_tray_application_scaffold",
  "layer": "desktop",
  "purpose": "Scaffold for tray-style background apps: menu model with invokable callbacks, a stoppable tick-based run loop, hotkey registry with dispatch, toasts delegated to scrapyard.desktop.toast_notifications, and console forms with injectable input (EOF-safe). Rendering an actual OS tray icon requires a GUI toolkit (e.g. pystray) that plugs into run().",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "menu item dicts {label, callback}; hotkey strings; form field defs {label, type, default}.",
  "outputs": "Invoked callbacks, collected form values, toast notifications.",
  "files_created": [],
  "security_notes": "Menu/hotkey callbacks execute with the app's privileges - register only functions you own, never callables built from external data. Form input is returned raw; validate before use.",
  "ai_usage": "SystemTrayApplication(icon, items).run(tick=fn, interval=..); HotkeyManager.register_hotkey/dispatch; Form(fields, input_fn=..).show() for scripted/headless input.",
  "example": "from scrapyard.desktop.system_tray_application_scaffold import SystemTrayApplication; app = SystemTrayApplication('icon.png', [{'label': 'Quit', 'callback': lambda: app.stop()}])",
  "import_path": "scrapyard.desktop.system_tray_application_scaffold"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

STATUS = "core"

logger = logging.getLogger(__name__)


class Menu:
    """Ordered tray menu model; items are (label, callback) and invokable."""

    def __init__(self):
        self.items: List[tuple] = []

    def add_item(self, label: str, callback: Callable) -> None:
        if not callable(callback):
            raise TypeError(f"callback for {label!r} must be callable")
        self.items.append((label, callback))

    def invoke(self, label: str) -> Any:
        """Run the callback registered under *label* (menu click)."""
        for item_label, callback in self.items:
            if item_label == label:
                return callback()
        raise KeyError(f"no menu item labelled {label!r}")


class SystemTrayApplication:
    """Background-app skeleton: holds the menu, runs a stoppable loop.

    The loop calls `tick` every `interval` seconds until stop() is called —
    a real tray backend (pystray, PyQt) can drive its own loop and still use
    this menu model + stop flag.
    """

    def __init__(self, icon_path: str, menu_items: List[Dict[str, Any]]):
        self.icon_path = icon_path
        self.menu = Menu()
        self._stop = threading.Event()
        for item in menu_items:
            label, callback = item.get("label"), item.get("callback")
            if label and callback:
                self.menu.add_item(label, callback)

    def create_menu(self) -> Menu:
        return self.menu

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return not self._stop.is_set()

    def run(self, tick: Optional[Callable[[], None]] = None,
            interval: float = 0.5, max_seconds: Optional[float] = None) -> int:
        """Run until stop() (or max_seconds). Returns the number of ticks."""
        self._stop.clear()
        deadline = time.monotonic() + max_seconds if max_seconds else None
        ticks = 0
        logger.info("SystemTrayApplication running (icon=%s)", self.icon_path)
        while not self._stop.is_set():
            if tick is not None:
                tick()
            ticks += 1
            if deadline is not None and time.monotonic() >= deadline:
                break
            self._stop.wait(interval)
        logger.info("SystemTrayApplication stopped after %d tick(s)", ticks)
        return ticks


class HotkeyManager:
    """Registry mapping hotkey strings to callback lists, with dispatch."""

    def __init__(self):
        self.hotkeys: Dict[str, List[Callable]] = {}

    def register_hotkey(self, key: str, callback: Callable) -> None:
        if not callable(callback):
            raise TypeError("hotkey callback must be callable")
        self.hotkeys.setdefault(key, []).append(callback)

    def unregister_hotkey(self, key: str) -> None:
        self.hotkeys.pop(key, None)

    def dispatch(self, key: str) -> int:
        """Fire all callbacks for *key*; returns how many ran."""
        callbacks = self.hotkeys.get(key, [])
        for cb in callbacks:
            cb()
        return len(callbacks)


def show_toast(icon: str, title: str, message: str, dry_run: bool = False) -> str:
    """Delegate to the real toast part; returns the backend used."""
    from scrapyard.desktop.toast_notifications import show_toast as _real_toast
    return _real_toast(title, message, icon=icon, dry_run=dry_run)


class ToastNotification:
    def __init__(self, icon: str, title: str, message: str):
        self.icon = icon
        self.title = title
        self.message = message

    def show(self, dry_run: bool = False) -> str:
        return show_toast(self.icon, self.title, self.message, dry_run=dry_run)


class Form:
    """Console form. `input_fn` injects answers (tests / non-tty); EOF or a
    missing answer falls back to the field's 'default' instead of crashing."""

    def __init__(self, fields: List[Dict], input_fn: Optional[Callable[[str], str]] = None):
        self.fields = fields
        self.input_fn = input_fn
        self.input_values: Dict[str, Any] = {}

    def show(self) -> Dict[str, Any]:
        reader = self.input_fn if self.input_fn is not None else input
        for field in self.fields:
            label = field["label"]
            default = field.get("default", "")
            try:
                value = reader(f"{label} [{default}]: ")
            except (EOFError, KeyboardInterrupt):
                value = ""
            self.input_values[label] = value if value else default
        return self.input_values


def create_form(fields: List[Dict],
                input_fn: Optional[Callable[[str], str]] = None) -> Form:
    return Form(fields, input_fn=input_fn)


def _selftest():
    logging.basicConfig(level=logging.INFO)

    # Menu: registration + click dispatch
    clicked = []
    app = SystemTrayApplication(
        icon_path="icon.png",
        menu_items=[{"label": "Exit", "callback": lambda: clicked.append("exit")}])
    menu = app.create_menu()
    assert isinstance(menu, Menu)
    menu.invoke("Exit")
    assert clicked == ["exit"], "menu callback did not fire"
    try:
        menu.invoke("Nope")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown menu label must raise")

    # Run loop: ticks, stops from inside a tick, bounded by max_seconds
    ticks_seen = []

    def tick():
        ticks_seen.append(1)
        if len(ticks_seen) >= 3:
            app.stop()

    n = app.run(tick=tick, interval=0.01, max_seconds=5)
    assert n >= 3 and not app.running, f"run loop misbehaved: {n} ticks"

    # Hotkeys: register, dispatch, unregister
    manager = HotkeyManager()
    fired = []
    manager.register_hotkey("Ctrl+Q", lambda: fired.append("q"))
    assert manager.dispatch("Ctrl+Q") == 1 and fired == ["q"]
    manager.unregister_hotkey("Ctrl+Q")
    assert manager.dispatch("Ctrl+Q") == 0

    # Toasts delegate to the real part (dry-run: headless-safe)
    assert show_toast("info", "Test Toast", "scaffold selftest", dry_run=True) == "dryrun"
    assert ToastNotification("info", "T", "m").show(dry_run=True) == "dryrun"

    # Form: scripted input, EOF falls back to defaults — never blocks
    answers = iter(["Ada"])

    def scripted(_prompt: str) -> str:
        try:
            return next(answers)
        except StopIteration:
            raise EOFError

    form = create_form([{"label": "Name", "type": "text", "default": "anon"},
                        {"label": "Age", "type": "number", "default": "0"}],
                       input_fn=scripted)
    result = form.show()
    assert result == {"Name": "Ada", "Age": "0"}, f"form values wrong: {result}"

    logger.info("Selftest completed successfully")


if __name__ == "__main__":
    _selftest()
