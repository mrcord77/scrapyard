"""
single_instance_locking — Prevent multiple copies of a desktop app from running: per-app lock rows in a shared SQLite db with stale-PID reclamation.

### PART-META-JSON
{
  "name": "single_instance_locking",
  "layer": "desktop",
  "purpose": "Single-instance guard: lock_application(app_name) records the PID in a per-user SQLite lock table and raises if a live instance already holds it; stale locks (dead PIDs) are reclaimed automatically.",
  "addition": true,
  "status": "core",
  "dependencies": ["psutil"],
  "inputs": "app_name string.",
  "outputs": "Lock row in %TEMP%/scrapyard_single_instance_locks/single_instance_locks.db; RuntimeError on duplicate launch; is_running() bool.",
  "files_created": ["<tempdir>/scrapyard_single_instance_locks/single_instance_locks.db"],
  "security_notes": "The lock db lives in the user temp dir and is advisory, not a security boundary - any local process can delete it. PID liveness via psutil can rarely collide with a recycled PID; treat as best-effort duplicate prevention, not mutual exclusion for correctness-critical state.",
  "ai_usage": "Call lock_application('myapp') once at startup; catch RuntimeError to exit when already running.",
  "example": "from scrapyard.desktop.single_instance_locking import lock_application; lock_application('myapp')",
  "import_path": "scrapyard.desktop.single_instance_locking"
}
### END-PART-META
"""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import time
import uuid
from typing import Optional

import psutil

__all__ = ["is_running", "lock_application"]

__parts_meta__ = {"name": "single_instance_locking", "layer": "desktop"}

logger = logging.getLogger(__name__)

_LOCK_DIR: Optional[str] = None
_current_app_name: Optional[str] = None
_lock_db_path: Optional[str] = None


def _default_lock_dir() -> str:
    return os.path.join(tempfile.gettempdir(), "scrapyard_single_instance_locks")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS single_instance_locks (
            app_name TEXT PRIMARY KEY,
            pid INTEGER NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.commit()


def _lock_db() -> str:
    lock_dir = _LOCK_DIR or _default_lock_dir()
    os.makedirs(lock_dir, exist_ok=True)
    return os.path.join(lock_dir, "single_instance_locks.db")


def is_running() -> bool:
    """Return True if the currently tracked application instance is still running."""
    global _lock_db_path
    if _current_app_name is None:
        return False

    db_path = _lock_db_path or _lock_db()
    if not os.path.exists(db_path):
        return False

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT pid FROM single_instance_locks WHERE app_name = ?",
            (_current_app_name,),
        ).fetchone()
        if row is None:
            return False

        pid: int = row[0]
        if psutil.pid_exists(pid):
            return True

        conn.execute(
            "DELETE FROM single_instance_locks WHERE app_name = ?",
            (_current_app_name,),
        )
        conn.commit()
        return False
    finally:
        conn.close()


def lock_application(app_name: str) -> None:
    """Acquire a single-instance lock for *app_name*.

    Raises:
        ValueError: If *app_name* is empty or not a string.
        RuntimeError: If another instance of the application is already running.
    """
    if not isinstance(app_name, str) or not app_name:
        raise ValueError("app_name must be a non-empty string")

    global _current_app_name, _lock_db_path
    _current_app_name = app_name

    db_path = _lock_db()
    _lock_db_path = db_path
    current_pid = os.getpid()

    conn = sqlite3.connect(db_path)
    try:
        _ensure_schema(conn)

        row = conn.execute(
            "SELECT pid FROM single_instance_locks WHERE app_name = ?",
            (app_name,),
        ).fetchone()

        if row is not None:
            existing_pid = row[0]
            if existing_pid == current_pid or psutil.pid_exists(existing_pid):
                raise RuntimeError(
                    f"Application {app_name!r} is already running (PID {existing_pid})."
                )
            conn.execute(
                "DELETE FROM single_instance_locks WHERE app_name = ?",
                (app_name,),
            )

        conn.execute(
            "INSERT INTO single_instance_locks (app_name, pid, created_at) "
            "VALUES (?, ?, ?)",
            (app_name, current_pid, time.time()),
        )
        conn.commit()
        logger.debug(
            "Acquired single-instance lock for %r (PID %d)", app_name, current_pid
        )
    finally:
        conn.close()


def _selftest() -> None:
    """Offline self-test using a temporary SQLite database."""
    global _LOCK_DIR, _current_app_name, _lock_db_path
    original_lock_dir = _LOCK_DIR
    original_app_name = _current_app_name
    original_lock_db_path = _lock_db_path

    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        _LOCK_DIR = tmp.name
        _current_app_name = None
        _lock_db_path = None

        app_name = f"scrapyard_single_instance_selftest_{uuid.uuid4().hex}"

        # Acquiring a fresh lock should succeed and report running.
        lock_application(app_name)
        assert is_running() is True, "is_running() should be True after locking"

        # A duplicate launch must raise.
        try:
            lock_application(app_name)
        except RuntimeError as exc:
            assert "already running" in str(exc).lower(), f"Unexpected error: {exc}"
        else:
            raise AssertionError("Duplicate lock_application() did not raise")

        # A stale lock (dead PID) should be ignored/replaced.
        conn = sqlite3.connect(_lock_db_path)
        try:
            conn.execute(
                "UPDATE single_instance_locks SET pid = ? WHERE app_name = ?",
                (999_999_999, app_name),
            )
            conn.commit()
        finally:
            conn.close()

        assert is_running() is False, "is_running() should be False for a stale lock"
        lock_application(app_name)
        assert is_running() is True, "is_running() should be True after reacquiring"
    finally:
        _LOCK_DIR = original_lock_dir
        _current_app_name = original_app_name
        _lock_db_path = original_lock_db_path
        tmp.cleanup()


if __name__ == "__main__":
    _selftest()
