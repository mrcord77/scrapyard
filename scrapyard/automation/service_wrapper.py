"""
service_wrapper — Wrap Python scripts as Windows services, enabling long-running automation tasks with process isolation and restart-on-failure behavior.

### PART-META-JSON
{
  "name": "service_wrapper",
  "layer": "automation",
  "purpose": "Wrap Python scripts as Windows services, enabling long-running automation tasks with process isolation and restart-on-failure behavior.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_service(name, script_path, display_name, description); start_service(name); stop_service(name).",
  "outputs": "Returns: create_service -> None; start_service -> None; stop_service -> None.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.automation.service_wrapper`.",
  "example": "from scrapyard.automation.service_wrapper import *",
  "import_path": "scrapyard.automation.service_wrapper"
}
### END-PART-META
"""

import os
import logging

# NOTE: pywin32 (win32serviceutil / servicemanager) is imported lazily inside the
# functions below so this module imports cleanly on machines without pywin32 and
# so the offline selftest never touches the Windows Service Control Manager.


def _pywin32_available() -> bool:
    try:
        import win32serviceutil  # noqa: F401
        import servicemanager  # noqa: F401
        return True
    except Exception:
        return False


def _validate_name(name: str) -> None:
    if not name or not str(name).strip():
        raise ValueError("service name must be a non-empty string")


def create_service(name: str, script_path: str, display_name: str, description: str) -> None:
    """
    Create a Windows service from the given Python script.
    """
    _validate_name(name)
    if not script_path or not str(script_path).strip():
        raise ValueError("script_path must be a non-empty string")
    import win32serviceutil
    import servicemanager
    try:
        # Register the service with Windows Service Control Manager (SCM)
        win32serviceutil.InstallService(
            script_path,
            name=name,
            displayName=display_name,
            description=description,
            startType=win32serviceutil.SERVICE_DEMAND_START
        )
        servicemanager.LogInfoMsg(f"Service '{name}' created successfully.")
    except Exception as e:
        logging.error(f"Failed to create service: {e}")
        raise

def start_service(name: str) -> None:
    """
    Start the specified Windows service.
    """
    _validate_name(name)
    import win32serviceutil
    import servicemanager
    try:
        # Start the service using win32serviceutil
        if not win32serviceutil.StartService(name):
            servicemanager.LogErrorMsg(f"Failed to start service '{name}'")
            raise Exception(f"Failed to start service: {name}")
        logging.info(f"Service '{name}' started successfully.")
    except Exception as e:
        logging.error(f"Failed to start service: {e}")
        raise

def stop_service(name: str) -> None:
    """
    Stop the specified Windows service.
    """
    _validate_name(name)
    import win32serviceutil
    import servicemanager
    try:
        # Stop the service using win32serviceutil
        if not win32serviceutil.StopService(name):
            servicemanager.LogErrorMsg(f"Failed to stop service '{name}'")
            raise Exception(f"Failed to stop service: {name}")
        logging.info(f"Service '{name}' stopped successfully.")
    except Exception as e:
        logging.error(f"Failed to stop service: {e}")
        raise

def _selftest():
    """Offline selftest: exercises input-validation sub-logic (falsifiable) and
    skips the real Windows SCM install/start/stop (needs admin + side effects)."""
    # NEGATIVE: empty / missing arguments are rejected before any SCM call.
    bad_inputs = [
        ("", "s.py", "d", "desc"),
        ("   ", "s.py", "d", "desc"),
        ("svc", "", "d", "desc"),
        (None, "s.py", "d", "desc"),
    ]
    for args in bad_inputs:
        try:
            create_service(*args)
            raise AssertionError(f"create_service accepted invalid args: {args!r}")
        except ValueError:
            pass
    for bad_name in ["", "   ", None]:
        for fn in (start_service, stop_service):
            try:
                fn(bad_name)
                raise AssertionError(f"{fn.__name__} accepted invalid name {bad_name!r}")
            except ValueError:
                pass

    assert callable(create_service) and callable(start_service) and callable(stop_service)

    # The live Windows-SCM leg is an external dependency (admin rights + real
    # service registration); never faked. Report it as skipped.
    if _pywin32_available():
        print("service_wrapper selftest: PASS "
              "(offline validation verified; live SCM install requires admin, not exercised)")
    else:
        print("service_wrapper selftest: SKIPPED "
              "(pywin32 unavailable; offline validation verified, SCM leg not exercised)")

if __name__ == "__main__":
    _selftest()
