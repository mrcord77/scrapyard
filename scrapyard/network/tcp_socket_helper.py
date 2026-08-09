"""
tcp_socket_helper — TCP connect with retry/backoff plus timed send/receive.

### PART-META-JSON
{
  "name": "tcp_socket_helper",
  "layer": "network",
  "purpose": "TCP client helpers: create_connection with retries and exponential backoff, send_data/receive_data with timeouts translated to ConnectionError.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Host/port/timeout/retries for create_connection; a connected socket and bytes for send/receive.",
  "outputs": "Connected socket objects; bytes sent counts; received bytes.",
  "files_created": [],
  "security_notes": "Plain TCP without TLS - wrap with ssl before sending sensitive data. Inputs are validated before any network call; failed sockets are always closed. Selftest is offline (mock socket, no real connections).",
  "ai_usage": "sock = create_connection(host, port, timeout=5, retries=3); send_data(sock, b'...'); data = receive_data(sock).",
  "example": "from scrapyard.network.tcp_socket_helper import create_connection, send_data, receive_data",
  "import_path": "scrapyard.network.tcp_socket_helper"
}
### END-PART-META
"""

import os
import sqlite3
import time
import logging
from socket import socket, AF_INET, SOCK_STREAM, timeout as SocketTimeout, error as SocketError
from tempfile import TemporaryDirectory
from typing import Optional

logger = logging.getLogger(__name__)


def create_connection(
    host: str,
    port: int,
    timeout: float = 10.0,
    retries: int = 3,
) -> socket:
    """
    Create a TCP connection to ``host:port`` with retry and exponential backoff.

    Parameters
    ----------
    host:
        Target hostname or IP address.
    port:
        Target port number.
    timeout:
        Connection timeout in seconds.
    retries:
        Number of retry attempts after the first failure.

    Returns
    -------
    socket.socket
        A connected TCP socket.

    Raises
    ------
    ValueError
        If inputs are invalid.
    ConnectionRefusedError
        If the connection cannot be established after all retries.
    """
    if not isinstance(host, str) or not host:
        raise ValueError("host must be a non-empty string")
    if not isinstance(port, int) or not (0 <= port <= 65535):
        raise ValueError("port must be an integer between 0 and 65535")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be a positive number")
    if not isinstance(retries, int) or retries < 0:
        raise ValueError("retries must be a non-negative integer")

    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        sock: Optional[socket] = None
        try:
            sock = socket(AF_INET, SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            return sock
        except (ConnectionRefusedError, SocketTimeout, SocketError, OSError) as exc:
            last_exc = exc
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            if attempt < retries:
                wait_time = 2 ** attempt
                logger.warning(
                    "Connection attempt %d to %s:%d failed: %s; retrying in %.1f seconds",
                    attempt + 1,
                    host,
                    port,
                    exc,
                    wait_time,
                )
                time.sleep(wait_time)
            else:
                raise ConnectionRefusedError(
                    f"Could not establish connection with {host}:{port} after {retries} retries"
                ) from exc


def send_data(sock: socket, data: bytes, timeout: float = 10.0) -> int:
    """
    Send all bytes over ``sock`` with a timeout.

    Returns
    -------
    int
        The number of bytes sent.

    Raises
    ------
    TypeError
        If ``sock`` is not a socket or ``data`` is not bytes.
    ValueError
        If ``timeout`` is not positive.
    ConnectionError
        If the send operation times out.
    """
    if not isinstance(sock, socket):
        raise TypeError("sock must be a socket instance")
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be a positive number")

    sock.settimeout(timeout)
    try:
        sock.sendall(data)
    except SocketTimeout as exc:
        raise ConnectionError(
            f"Send operation timed out after {timeout} seconds"
        ) from exc
    return len(data)


def receive_data(
    sock: socket, buffer_size: int = 4096, timeout: float = 10.0
) -> bytes:
    """
    Receive up to ``buffer_size`` bytes from ``sock`` with a timeout.

    Returns
    -------
    bytes
        Data received from the socket.

    Raises
    ------
    TypeError
        If ``sock`` is not a socket.
    ValueError
        If ``buffer_size`` or ``timeout`` is invalid.
    ConnectionError
        If the receive operation times out.
    """
    if not isinstance(sock, socket):
        raise TypeError("sock must be a socket instance")
    if not isinstance(buffer_size, int) or buffer_size <= 0:
        raise ValueError("buffer_size must be a positive integer")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be a positive number")

    sock.settimeout(timeout)
    try:
        return sock.recv(buffer_size)
    except SocketTimeout as exc:
        raise ConnectionError(
            f"Receive operation timed out after {timeout} seconds"
        ) from exc


def _selftest() -> None:
    """
    Offline self-test using mocks and a temporary SQLite database.
    """
    global socket

    original_socket = socket
    original_sleep = time.sleep

    class FakeSocket:
        """
        A mock socket for offline testing.
        """

        def __init__(
            self,
            sendall_raises: Optional[Exception] = None,
            recv_returns: bytes = b"",
            recv_raises: Optional[Exception] = None,
        ):
            self.sendall_raises = sendall_raises
            self.recv_returns = recv_returns
            self.recv_raises = recv_raises
            self.sent: bytes = b""

        def settimeout(self, value: float) -> None:
            pass

        def connect(self, address) -> None:
            raise ConnectionRefusedError(111, "Connection refused")

        def sendall(self, data: bytes) -> None:
            if self.sendall_raises is not None:
                raise self.sendall_raises
            self.sent += data

        def recv(self, bufsize: int) -> bytes:
            if self.recv_raises is not None:
                raise self.recv_raises
            return self.recv_returns

        def close(self) -> None:
            pass

    try:
        time.sleep = lambda _seconds: None
        socket = FakeSocket

        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = os.path.join(temp_dir, "selftest.db")
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS _selftest (id INTEGER PRIMARY KEY)"
                )
                conn.execute("INSERT INTO _selftest DEFAULT VALUES")
                conn.commit()
                row = conn.execute(
                    "SELECT COUNT(*) FROM _selftest"
                ).fetchone()
                assert row is not None and row[0] == 1
            finally:
                conn.close()

        # Invalid host/port validation must reject bad inputs without network IO.
        try:
            create_connection("", 12345)
            assert False, "create_connection should raise ValueError for empty host"
        except ValueError:
            pass

        try:
            create_connection("localhost", 99999)
            assert False, "create_connection should raise ValueError for invalid port"
        except ValueError:
            pass

        # Connection refused after all retries should raise a clear error.
        try:
            create_connection("localhost", 8080, timeout=1.0, retries=3)
            assert False, "create_connection should raise ConnectionRefusedError"
        except ConnectionRefusedError as exc:
            assert (
                str(exc)
                == "Could not establish connection with localhost:8080 after 3 retries"
            )

        # send_data should return the number of bytes sent, not zero.
        fake_sock = FakeSocket(recv_returns=b"Mocked data")
        sent = send_data(fake_sock, b"Test data")
        assert sent == len(b"Test data"), "send_data returned wrong byte count"
        assert sent > 0, "send_data should return a positive byte count on success"

        # receive_data should return the expected payload.
        received = receive_data(fake_sock, buffer_size=4096)
        assert received == b"Mocked data", "receive_data returned unexpected data"

        # Timeout on send should be translated to ConnectionError.
        timeout_sock = FakeSocket(sendall_raises=SocketTimeout())
        try:
            send_data(timeout_sock, b"x")
            assert False, "send_data should raise on timeout"
        except ConnectionError:
            pass

        # Timeout on receive should be translated to ConnectionError.
        recv_timeout_sock = FakeSocket(recv_raises=SocketTimeout())
        try:
            receive_data(recv_timeout_sock)
            assert False, "receive_data should raise on timeout"
        except ConnectionError:
            pass

    finally:
        socket = original_socket
        time.sleep = original_sleep


if __name__ == "__main__":
    _selftest()
