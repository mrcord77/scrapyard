"""
process_launcher — The `process_launcher` module provides tools to launch, monitor, and manage system processes, enabling automation workflows with robust supervision and control.

### PART-META-JSON
{
  "name": "process_launcher",
  "layer": "automation",
  "purpose": "The `process_launcher` module provides tools to launch, monitor, and manage system processes, enabling automation workflows with robust supervision and control.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: launch_process(cmd, args, timeout); register_task(name, interval, func); read_clipboard(); write_clipboard(data); send_notification(title, message); ProcessSupervisor(...); FileWatcher(...); TaskManager(...) (plus more).",
  "outputs": "Returns: launch_process -> subprocess.Popen; register_task -> None; read_clipboard -> str; write_clipboard -> None; send_notification -> None.",
  "files_created": [],
  "security_notes": "Invokes subprocesses; never pass unsanitized input as command arguments. Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.automation.process_launcher`.",
  "example": "from scrapyard.automation.process_launcher import *",
  "import_path": "scrapyard.automation.process_launcher"
}
### END-PART-META
"""
import os
import time
import logging
import subprocess
import threading
from typing import Any, Callable, Optional, Dict

logger = logging.getLogger(__name__)


class ProcessSupervisor:
    def __init__(self, process: subprocess.Popen):
        self.process = process

    def monitor(self, interval: float = 1.0, timeout: Optional[float] = None) -> None:
        """Monitor process until it terminates or timeout is reached."""
        start_time = time.time()
        while True:
            if self.process.poll() is not None:
                break
            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    raise subprocess.TimeoutExpired(self.process.args, timeout)
            time.sleep(interval)

    def terminate(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.monitor(timeout=5.0)
        except subprocess.TimeoutExpired:
            logger.warning("Process did not terminate, killing it.")
            self.process.kill()
            self.process.wait()


def launch_process(cmd: str, args: list[str], timeout: float = 30.0) -> subprocess.Popen:
    process = subprocess.Popen([cmd] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    supervisor = ProcessSupervisor(process)
    try:
        supervisor.monitor(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("Process did not complete within the timeout period.")
        supervisor.terminate()
    return process


class FileWatcher:
    def __init__(self, path: str, callback: Callable[[str], None]):
        self.path = path
        self.callback = callback
        self._observer: Optional[Any] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._running = False
        self._last_mtime: float = 0

    def start(self) -> None:
        try:
            import watchdog.observers
            from watchdog.events import FileSystemEventHandler

            class Watcher(FileSystemEventHandler):
                def __init__(self, watcher_instance: 'FileWatcher'):
                    self.watcher_instance = watcher_instance
                    super().__init__()

                def on_modified(self, event):
                    if not event.is_directory and event.src_path == self.watcher_instance.path:
                        self.watcher_instance.callback(event.src_path)

            self._observer = watchdog.observers.Observer()
            handler = Watcher(self)
            watch_dir = os.path.dirname(self.path) or '.'
            self._observer.schedule(handler, watch_dir, recursive=False)
            self._observer.start()
            self._running = True
        except ImportError:
            logger.debug("watchdog not available, using polling fallback")
            self._start_polling()

    def _start_polling(self):
        self._running = True
        if os.path.exists(self.path):
            self._last_mtime = os.path.getmtime(self.path)
        
        def poll():
            while self._running:
                try:
                    if os.path.exists(self.path):
                        current_mtime = os.path.getmtime(self.path)
                        if current_mtime != self._last_mtime:
                            self._last_mtime = current_mtime
                            self.callback(self.path)
                except Exception as e:
                    logger.error(f"Error polling file: {e}")
                time.sleep(1.0)
        
        self._poll_thread = threading.Thread(target=poll, daemon=True)
        self._poll_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join()
            except Exception as e:
                logger.error(f"Error stopping observer: {e}")
            self._observer = None


# Global registry to prevent timer garbage collection
_tasks: Dict[str, threading.Timer] = {}


def register_task(name: str, interval: float, func: Callable[[], Any]) -> None:
    def wrapper():
        if name not in _tasks:
            return
        logger.info(f"Task '{name}' started.")
        try:
            func()
        except Exception as e:
            logger.error(f"Task '{name}' error: {e}")
        # Reschedule if still registered
        if name in _tasks:
            timer = threading.Timer(interval, wrapper)
            timer.daemon = True
            _tasks[name] = timer
            timer.start()

    timer = threading.Timer(interval, wrapper)
    timer.daemon = True
    _tasks[name] = timer
    timer.start()


class TaskManager:
    def __init__(self):
        self._local_tasks: Dict[str, threading.Timer] = {}
        self._running = False

    def start(self) -> None:
        self._running = True
        logger.info("TaskManager started")

    def stop(self) -> None:
        self._running = False
        # Cancel tasks registered via register_task that we manage
        for name in list(_tasks.keys()):
            _tasks[name].cancel()
            del _tasks[name]
        logger.info("TaskManager stopped")


def read_clipboard() -> str:
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        data = win32clipboard.GetClipboardData()
        win32clipboard.CloseClipboard()
        return data
    except Exception:
        return ""


def write_clipboard(data: str) -> None:
    try:
        import win32clipboard
        import win32con
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, data)
        win32clipboard.CloseClipboard()
    except Exception:
        pass


def send_notification(title: str, message: str) -> None:
    try:
        import win10toast
        toast = win10toast.ToastNotifier()
        toast.show_toast(title, message, duration=2, threaded=True)
    except Exception:
        logger.info(f"Notification [{title}]: {message}")


class WindowManager:
    def focus_window(self, title: str) -> None:
        try:
            import win32gui
            
            def enum_callback(hwnd, extra):
                if win32gui.IsWindowVisible(hwnd):
                    text = win32gui.GetWindowText(hwnd)
                    if title.lower() in text.lower():
                        win32gui.SetForegroundWindow(hwnd)
                        return False
                return True
            
            win32gui.EnumWindows(enum_callback, None)
        except Exception:
            env = os.environ.copy()
            env["SCRAPYARD_WINDOW_TITLE"] = title
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "$wshell = New-Object -ComObject wscript.shell; "
                    "$wshell.AppActivate($env:SCRAPYARD_WINDOW_TITLE)",
                ],
                capture_output=True,
                check=False,
                env=env,
            )

    def close_window(self, title: str) -> None:
        try:
            import win32gui
            import win32con
            
            def enum_callback(hwnd, extra):
                if win32gui.IsWindowVisible(hwnd):
                    text = win32gui.GetWindowText(hwnd)
                    if title.lower() in text.lower():
                        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                        return False
                return True
            
            win32gui.EnumWindows(enum_callback, None)
        except Exception:
            logger.warning(
                "Unable to close window %r because the native Windows API "
                "is unavailable",
                title,
            )


def _selftest():
    """Offline, deterministic, headless-safe. Exercises the real process-launch
    and supervision API against the Python interpreter itself (always present,
    cross-platform) — no GUI apps, no clipboard, no notifications, no side
    effects that touch the desktop."""
    import sys
    import tempfile

    logger.info("Starting self-test")
    py = sys.executable

    # --- launch_process(): a short command runs to completion with exit code 0
    #     and its stdout is captured.
    process = launch_process(py, ['-c', 'print("scrapyard-ok")'])
    assert process.poll() is not None, "launch_process must return a terminated process"
    out, _ = process.communicate()
    assert process.returncode == 0, f"expected rc 0, got {process.returncode}"
    assert b"scrapyard-ok" in out, f"captured stdout missing marker: {out!r}"

    # --- non-zero exit is reported faithfully (lifecycle, not just 'it ran').
    failing = launch_process(py, ['-c', 'import sys; sys.exit(3)'])
    failing.communicate()
    assert failing.returncode == 3, f"expected rc 3, got {failing.returncode}"

    # --- ProcessSupervisor.terminate() stops a long-running process deterministically.
    long_proc = subprocess.Popen(
        [py, '-c', 'import time; time.sleep(30)'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    supervisor = ProcessSupervisor(long_proc)
    supervisor.terminate()
    assert long_proc.poll() is not None, "Supervisor did not terminate the process"

    # --- Negative case: a nonexistent binary must raise, not silently pass.
    raised = False
    try:
        launch_process('scrapyard_no_such_binary_xyz', ['--nope'])
    except (FileNotFoundError, OSError):
        raised = True
    assert raised, "launching a nonexistent binary must raise"

    # --- FileWatcher via the cross-platform polling fallback (no GUI, no desktop).
    callback_triggered = threading.Event()
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        test_file = f.name
        f.write("initial")
    watcher = None
    try:
        watcher = FileWatcher(test_file, lambda path: callback_triggered.set())
        watcher._start_polling()          # force deterministic polling backend
        time.sleep(0.2)
        with open(test_file, 'a') as fh:
            fh.write(" modified")
        callback_triggered.wait(timeout=5)
        assert callback_triggered.is_set(), "FileWatcher callback was not triggered"
    finally:
        if watcher:
            watcher.stop()
        if os.path.exists(test_file):
            os.unlink(test_file)

    # --- register_task(): the scheduled callable actually fires, then we clean up.
    task_flag = threading.Event()
    register_task("test_task_selftest", 0.2, task_flag.set)
    task_flag.wait(timeout=3)
    assert task_flag.is_set(), "register_task callable did not run"
    if "test_task_selftest" in _tasks:
        _tasks["test_task_selftest"].cancel()
        del _tasks["test_task_selftest"]

    # --- TaskManager lifecycle is clean.
    tm = TaskManager()
    tm.start()
    tm.stop()

    logger.info("All tests passed")
    print("process_launcher selftest passed")


if __name__ == "__main__":
    import sys as _sys
    _selftest()
    _sys.exit(0)
