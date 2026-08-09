"""
network_status — Report internet connectivity for desktop applications via a TCP reachability probe with retries and backoff.

### PART-META-JSON
{
  "name": "network_status",
  "layer": "desktop",
  "purpose": "Internet connectivity check: TCP connect to 8.8.8.8:53 with configurable timeout/retries; selftest is fully offline via socket mocks.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "timeout seconds, retry count.",
  "outputs": "is_connected_to_internet() -> bool.",
  "files_created": [],
  "security_notes": "Performs an outbound TCP connection to Google Public DNS when called for real - a network side effect some environments (air-gapped, egress-filtered) disallow; the connection carries no payload.",
  "ai_usage": "Import what you need from `scrapyard.desktop.network_status`.",
  "example": "from scrapyard.desktop.network_status import *",
  "import_path": "scrapyard.desktop.network_status"
}
### END-PART-META
"""

import logging
import socket
import time
from typing import Optional

# Module-level logger
logger = logging.getLogger(__name__)


def is_connected_to_internet(timeout: float = 5, retry: int = 3) -> bool:
    """Check if the system is connected to the internet.
    
    Attempts to establish a TCP connection to a reliable external host
    (Google Public DNS 8.8.8.8:53) to verify internet connectivity.
    Uses socket for minimal dependencies and no external libraries.
    
    Thread-safe: Each call creates independent socket connections.
    Non-blocking: Respects the timeout parameter for each attempt.
    
    Args:
        timeout: Connection timeout in seconds for each attempt. Default 5.
        retry: Number of retry attempts before returning False. Default 3.
        
    Returns:
        True if internet connection is detected, False otherwise.
    """
    # Google Public DNS - reliable and fast
    host = "8.8.8.8"
    port = 53
    
    for attempt in range(retry):
        sock: Optional[socket.socket] = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            logger.debug(f"Internet connectivity confirmed on attempt {attempt + 1}")
            return True
        except OSError as exc:
            logger.debug(f"Connection attempt {attempt + 1} failed: {exc}")
            if attempt < retry - 1:
                time.sleep(0.1 * (attempt + 1))  # Brief backoff
        except Exception as exc:
            logger.debug(f"Unexpected error on attempt {attempt + 1}: {exc}")
            if attempt < retry - 1:
                time.sleep(0.1)
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
    
    logger.debug(f"Internet connectivity check failed after {retry} attempts")
    return False


def _selftest() -> None:
    """Run module self-test to verify functionality without network access.
    
    Tests:
    - is_connected_to_internet() returns False when offline (simulated)
    - is_connected_to_internet() returns True when online (simulated)
    - Retry logic functions correctly
    - No exceptions raised during execution
    - Completes in under 20 seconds
    
    This test works entirely offline by mocking socket operations.
    """
    logger.info("Starting network_status selftest")
    
    # Save original socket class
    original_socket = socket.socket
    
    # Test 1: Simulate offline conditions (network unreachable)
    class FailingSocket:
        """Mock socket that simulates network failure."""
        
        def __init__(self, *args, **kwargs) -> None:
            raise OSError("Network is unreachable [mocked]")
        
        def close(self) -> None:
            pass
    
    try:
        socket.socket = FailingSocket  # type: ignore
        result = is_connected_to_internet(timeout=0.1, retry=2)
        assert result is False, f"Expected False when offline, got {result}"
        logger.info("Offline detection test passed")
    finally:
        socket.socket = original_socket
    
    # Test 2: Simulate online conditions (connection successful)
    class SuccessfulSocket:
        """Mock socket that simulates successful connection."""
        
        def __init__(self, *args, **kwargs) -> None:
            pass
        
        def settimeout(self, value: float) -> None:
            pass
        
        def connect(self, address: tuple) -> None:
            pass
        
        def close(self) -> None:
            pass
    
    try:
        socket.socket = SuccessfulSocket  # type: ignore
        result = is_connected_to_internet(timeout=0.1, retry=1)
        assert result is True, f"Expected True when online, got {result}"
        logger.info("Online detection test passed")
    finally:
        socket.socket = original_socket
    
    # Test 3: Verify retry logic works (first attempts fail, then succeed)
    class IntermittentSocket:
        """Mock socket that fails first N times then succeeds."""
        _fail_count: int = 0
        
        def __init__(self, *args, **kwargs) -> None:
            if IntermittentSocket._fail_count < 2:
                IntermittentSocket._fail_count += 1
                raise OSError("Connection refused [mocked]")
        
        def settimeout(self, value: float) -> None:
            pass
        
        def connect(self, address: tuple) -> None:
            pass
        
        def close(self) -> None:
            pass
    
    try:
        IntermittentSocket._fail_count = 0
        socket.socket = IntermittentSocket  # type: ignore
        result = is_connected_to_internet(timeout=0.1, retry=3)
        assert result is True, f"Expected True with retry logic, got {result}"
        assert IntermittentSocket._fail_count == 2, f"Expected 2 failures, got {IntermittentSocket._fail_count}"
        logger.info("Retry logic test passed")
    finally:
        socket.socket = original_socket
    
    logger.info("network_status selftest completed successfully")


if __name__ == "__main__":
    _selftest()
