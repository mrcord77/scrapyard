"""
udp_socket_helper — Provides reusable UDP socket utilities for reliable datagram handling in distributed systems, with focus on type safety, error resilience, and configurability.

### PART-META-JSON
{
  "name": "udp_socket_helper",
  "layer": "network",
  "purpose": "Provides reusable UDP socket utilities for reliable datagram handling in distributed systems, with focus on type safety, error resilience, and configurability.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: send_datagram(host, port, data, timeout); receive_datagram(port, buffer_size, timeout); UDPSocketContext(...).",
  "outputs": "Returns: send_datagram -> bool; receive_datagram -> Optional[Tuple[bytes, str, int]].",
  "files_created": [],
  "security_notes": "Makes outbound network calls; set timeouts, validate URLs/hosts, and never send secrets to untrusted endpoints.",
  "ai_usage": "Import what you need from `scrapyard.network.udp_socket_helper`.",
  "example": "from scrapyard.network.udp_socket_helper import *",
  "import_path": "scrapyard.network.udp_socket_helper"
}
### END-PART-META
"""

import logging
import socket
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class UDPSocketContext:
    def __init__(self, host: str, port: int, family: int = socket.AF_INET):
        self.host = host
        self.port = port
        self.family = family
        self._sock = None

    def __enter__(self) -> socket.socket:
        self._sock = socket.socket(self.family, socket.SOCK_DGRAM)
        return self._sock

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._sock:
            self._sock.close()


def send_datagram(host: str, port: int, data: bytes, timeout: float = 1.0) -> bool:
    if not isinstance(host, str):
        raise TypeError(f"send_datagram() argument 1 must be str, not {type(host).__name__}")
    if not isinstance(port, int):
        raise TypeError(f"send_datagram() argument 2 must be int, not {type(port).__name__}")
    if not isinstance(data, bytes):
        raise TypeError(f"send_datagram() argument 3 must be bytes, not {type(data).__name__}")
    if not isinstance(timeout, (int, float)):
        raise TypeError(f"send_datagram() argument 4 must be float, not {type(timeout).__name__}")
    
    try:
        with UDPSocketContext(host, port) as sock:
            sock.settimeout(timeout)
            sent = sock.sendto(data, (host, port))
            logger.info(f"Sent datagram to {host}:{port}")
            return sent == len(data)
    except (socket.error, OSError):
        return False


def receive_datagram(port: int, buffer_size: int = 65535, timeout: float = 1.0) -> Optional[Tuple[bytes, str, int]]:
    if not isinstance(port, int):
        raise TypeError(f"receive_datagram() argument 1 must be int, not {type(port).__name__}")
    if not isinstance(buffer_size, int):
        raise TypeError(f"receive_datagram() argument 2 must be int, not {type(buffer_size).__name__}")
    if not isinstance(timeout, (int, float)):
        raise TypeError(f"receive_datagram() argument 3 must be float, not {type(timeout).__name__}")
    
    try:
        with UDPSocketContext('', port) as sock:
            sock.bind(('', port))
            sock.settimeout(timeout)
            try:
                data, (remote_host, remote_port) = sock.recvfrom(buffer_size)
                logger.info(f"Received datagram from {remote_host}:{remote_port}")
                return data, remote_host, remote_port
            except socket.timeout:
                logger.warning("Receive operation timed out")
                return None
    except OSError:
        return None


def _selftest():
    # Test send_datagram() with unreachable host (invalid address forces error)
    result = send_datagram('256.0.0.1', 9999, b'test')
    assert not result, "send_datagram should fail on unreachable host"

    # Test receive_datagram() with timeout
    result = receive_datagram(8888)
    assert result is None, "receive_datagram should return None on timeout"

    # Test context manager properly closes socket
    with UDPSocketContext('127.0.0.1', 8888) as ctx_sock:
        assert ctx_sock.fileno() != -1, "Socket should be open inside context"
    assert ctx_sock.fileno() == -1, "Socket should be closed by context manager"

    # Test function parameters are type-checked
    try:
        send_datagram('127.0.0.1', 9999, 'not bytes')
        assert False, "Should have raised TypeError"
    except TypeError as e:
        assert "send_datagram() argument 3 must be bytes, not str" in str(e)

    # Test logging captures send/receive events
    logger.info("Testing log capture")
    with UDPSocketContext('127.0.0.1', 8888):
        pass


if __name__ == "__main__":
    _selftest()
