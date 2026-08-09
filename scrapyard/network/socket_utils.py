"""
socket_utils — Real TCP socket helpers: validated connect, send/recv primitives,
length-prefixed messaging, and centralized error handling.

### PART-META-JSON
{
  "name": "socket_utils",
  "layer": "network",
  "purpose": "Working socket operations - validated socket creation/connect, send_all/recv_exact/recv_until primitives, length-prefixed send_message/recv_message, safe close, and centralized socket error handling.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Host/port/timeout for connections; connected socket objects and bytes payloads for the I/O helpers.",
  "outputs": "Configured/connected socket objects; bytes received; framed message payloads.",
  "files_created": [],
  "security_notes": "Plain TCP - no TLS; wrap the socket with ssl.SSLContext before sending sensitive data. recv_message caps frames at max_size (default 16 MiB) to block length-prefix memory bombs; recv_until caps buffered bytes. All inputs are validated before any network call. Selftest uses socket.socketpair()/loopback only - no external network.",
  "ai_usage": "sock = connect_socket(host, port, timeout=5); send_message(sock, b'payload'); reply = recv_message(sock); close_socket(sock). Use handle_socket_error(exc, logger) in except blocks to suppress known socket errors.",
  "example": "from scrapyard.network.socket_utils import connect_socket, send_message, recv_message",
  "import_path": "scrapyard.network.socket_utils"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import socket
import struct
from typing import Optional

STATUS = "core"

DEFAULT_MAX_MESSAGE = 16 * 1024 * 1024  # 16 MiB frame cap


def handle_socket_error(exc: Exception, logger: logging.Logger) -> None:
    """Centralized socket error handling: log + suppress known socket errors
    (OSError, TimeoutError, ConnectionError, BrokenPipeError); re-raise the rest."""
    known_socket_errors = (OSError, TimeoutError, ConnectionError, BrokenPipeError)
    if isinstance(exc, known_socket_errors):
        logger.error(f"Socket error handled: {type(exc).__name__}: {exc}", exc_info=True)
        return
    raise exc


def _validate(host: str, port: int, timeout: float) -> None:
    if not isinstance(host, str):
        raise TypeError(f"host must be str, not {type(host).__name__}")
    if not host.strip():
        raise ValueError("host must be non-empty string")
    if not isinstance(port, int) or isinstance(port, bool):
        raise TypeError(f"port must be int, not {type(port).__name__}")
    if not (0 < port <= 65535):
        raise ValueError(f"port must be between 1 and 65535, got {port}")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise TypeError(f"timeout must be number, not {type(timeout).__name__}")
    if timeout <= 0:
        raise ValueError(f"timeout must be positive, got {timeout}")


def create_socket(host: str, port: int, timeout: float = 10.0) -> socket.socket:
    """Validate parameters and return a configured (unconnected) TCP socket.
    Caller owns the socket and must close it (or use close_socket)."""
    _validate(host, port, timeout)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    return sock


def connect_socket(host: str, port: int, timeout: float = 10.0) -> socket.socket:
    """Validate, create, and CONNECT a TCP socket. Returns the connected socket."""
    sock = create_socket(host, port, timeout)
    try:
        sock.connect((host, port))
    except Exception:
        sock.close()
        raise
    return sock


def common_socket_operations(host: str, port: int, timeout: float = 10.0) -> socket.socket:
    """Back-compat name: validated socket creation. Now RETURNS the configured
    socket instead of discarding it (use connect_socket to also connect)."""
    return create_socket(host, port, timeout)


def send_all(sock: socket.socket, data: bytes) -> int:
    """Send every byte of data (sendall); returns bytes sent."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like")
    sock.sendall(data)
    return len(data)


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly n bytes or raise ConnectionError on early EOF."""
    if n < 0:
        raise ValueError("n must be >= 0")
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(65536, n - len(buf)))
        if not chunk:
            raise ConnectionError(f"connection closed after {len(buf)}/{n} bytes")
        buf.extend(chunk)
    return bytes(buf)


def recv_until(sock: socket.socket, delimiter: bytes = b"\n",
               max_bytes: int = DEFAULT_MAX_MESSAGE) -> bytes:
    """Receive until delimiter (returned WITHOUT the delimiter); caps at max_bytes."""
    if not delimiter:
        raise ValueError("delimiter must be non-empty")
    # Byte-at-a-time so no bytes past the delimiter are consumed/lost.
    buf = bytearray()
    while not buf.endswith(delimiter):
        if len(buf) >= max_bytes:
            raise ValueError(f"no delimiter within {max_bytes} bytes")
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("connection closed before delimiter")
        buf.extend(chunk)
    return bytes(buf[:-len(delimiter)])


def send_message(sock: socket.socket, payload: bytes) -> int:
    """Send a 4-byte big-endian length-prefixed frame; returns total bytes sent."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("payload must be bytes-like")
    header = struct.pack(">I", len(payload))
    sock.sendall(header + bytes(payload))
    return 4 + len(payload)


def recv_message(sock: socket.socket, max_size: int = DEFAULT_MAX_MESSAGE) -> bytes:
    """Receive one length-prefixed frame; rejects frames larger than max_size."""
    (length,) = struct.unpack(">I", recv_exact(sock, 4))
    if length > max_size:
        raise ValueError(f"frame of {length} bytes exceeds max_size {max_size}")
    return recv_exact(sock, length)


def close_socket(sock: Optional[socket.socket]) -> None:
    """Shutdown + close, swallowing errors on already-dead sockets."""
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _selftest() -> None:
    import os
    import tempfile
    import threading

    test_logger = logging.getLogger("scrapyard.network.socket_utils._selftest")
    test_logger.setLevel(logging.DEBUG)

    # --- error handling ---
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        log_path = os.path.join(tmpdir, "test.log")
        handler = logging.FileHandler(log_path)
        handler.setFormatter(logging.Formatter('%(levelname)s:%(message)s'))
        test_logger.addHandler(handler)
        try:
            for suppressed in (OSError(111, "Connection refused"), TimeoutError("t"),
                               ConnectionRefusedError(), BrokenPipeError()):
                handle_socket_error(suppressed, test_logger)  # must not raise
            try:
                handle_socket_error(ValueError("not a socket error"), test_logger)
                raise AssertionError("ValueError should re-raise")
            except ValueError:
                pass
            handler.flush()
            with open(log_path) as f:
                content = f.read()
            assert content.count("Socket error handled") == 4
            assert "Connection refused" in content
        finally:
            handler.close()
            test_logger.removeHandler(handler)

    # --- validation ---
    for bad, exc in ((("", 80), ValueError), (("localhost", 0), ValueError),
                     (("localhost", 70000), ValueError), ((None, 80), TypeError),
                     (("localhost", "80"), TypeError)):
        try:
            create_socket(*bad)  # type: ignore[arg-type]
            raise AssertionError(f"accepted {bad}")
        except exc:
            pass
    try:
        create_socket("localhost", 80, timeout=-1)
        raise AssertionError("negative timeout accepted")
    except ValueError:
        pass
    s = common_socket_operations("127.0.0.1", 8080, 1.0)
    assert isinstance(s, socket.socket) and abs(s.gettimeout() - 1.0) < 1e-9
    close_socket(s)

    # --- REAL operations over a socketpair (offline) ---
    a, b = socket.socketpair()
    try:
        assert send_all(a, b"hello") == 5
        assert recv_exact(b, 5) == b"hello"

        send_all(a, b"line-one\nrest")
        assert recv_until(b, b"\n") == b"line-one"
        assert recv_exact(b, 4) == b"rest"

        # large payload: send from a thread so the socketpair buffer can drain
        payload = b"x" * 70000  # bigger than one recv chunk
        sender = threading.Thread(target=send_message, args=(a, payload))
        sender.start()
        assert recv_message(b) == payload
        sender.join(timeout=5)

        # frame cap blocks memory bombs
        send_message(a, b"tiny")
        try:
            recv_message(b, max_size=2)
            raise AssertionError("oversized frame accepted")
        except ValueError:
            pass
    finally:
        close_socket(a)
        close_socket(b)

    # --- connect/send/recv/close against a loopback listener ---
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def _serve():
        conn, _ = listener.accept()
        msg = recv_message(conn)
        send_message(conn, msg.upper())
        close_socket(conn)

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    client = connect_socket("127.0.0.1", port, timeout=5.0)
    try:
        send_message(client, b"ping")
        assert recv_message(client) == b"PING"
    finally:
        close_socket(client)
        t.join(timeout=5)
        listener.close()

    # early EOF surfaces as ConnectionError
    a, b = socket.socketpair()
    a.close()
    try:
        recv_exact(b, 10)
        raise AssertionError("EOF not detected")
    except ConnectionError:
        pass
    finally:
        close_socket(b)

    print("socket_utils selftest OK")


if __name__ == "__main__":
    _selftest()
    raise SystemExit(0)
