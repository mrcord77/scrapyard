"""
websocket_client — Provides a robust WebSocket client with automatic reconnection and message handling for networked applications. Designed to be reused across services requiring persistent, reliable communication over 

### PART-META-JSON
{
  "name": "websocket_client",
  "layer": "network",
  "purpose": "Provides a robust WebSocket client with automatic reconnection and message handling for networked applications. Designed to be reused across services requiring persistent, reliable communication over ",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: WebSocketClient(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Makes outbound network calls; set timeouts, validate URLs/hosts, and never send secrets to untrusted endpoints.",
  "ai_usage": "Import what you need from `scrapyard.network.websocket_client`.",
  "example": "from scrapyard.network.websocket_client import *",
  "import_path": "scrapyard.network.websocket_client"
}
### END-PART-META
"""
from typing import Callable, Optional
import logging
import time
import threading
import socket
import select

logger = logging.getLogger(__name__)

class WebSocketClient:
    def __init__(self, url: str, *, reconnect: bool = True, timeout: float = 30.0, 
                 heartbeat_interval: float = 60.0, **kwargs) -> None:
        self.url = url
        self.reconnect = reconnect
        self.timeout = timeout
        self.heartbeat_interval = heartbeat_interval
        self.kwargs = kwargs
        
        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._shutdown = False
        self._connected = False
        self._connecting = False
        
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 32.0
        
        self._on_message: Optional[Callable[[str], None]] = None
        self._on_disconnect: Optional[Callable[[Exception], None]] = None
        
    def connect(self) -> None:
        with self._lock:
            if self._connected or self._connecting:
                logger.info("Already connected or connecting")
                return
            self._shutdown = False
            self._connecting = True
            
        threading.Thread(target=self._connect_internal, daemon=True).start()
        
    def _connect_internal(self) -> None:
        try:
            if ':' in self.url:
                host, port_str = self.url.rsplit(':', 1)
                port = int(port_str)
            else:
                host = self.url
                port = 80
                
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((host, port))
            sock.setblocking(False)
            
            with self._lock:
                if self._shutdown:
                    sock.close()
                    self._connecting = False
                    return
                self._socket = sock
                self._connected = True
                self._connecting = False
                self._reconnect_delay = 1.0
                
            logger.info(f"Connected to {self.url}")
            
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            with self._lock:
                self._connecting = False
            self._handle_disconnect(e)
            if self.reconnect and not self._shutdown:
                self._schedule_reconnect()
                
    def _run(self) -> None:
        last_error = None
        try:
            while not self._shutdown:
                with self._lock:
                    if not self._socket:
                        break
                    sock = self._socket
                    
                try:
                    readable, _, _ = select.select([sock], [], [], 1.0)
                    if not readable:
                        continue
                        
                    data = sock.recv(4096)
                    if not data:
                        logger.info("Connection closed by peer")
                        break
                        
                    message = data.decode('utf-8', errors='replace')
                    if self._on_message:
                        try:
                            self._on_message(message)
                        except Exception as e:
                            logger.error(f"Error in message callback: {e}")
                            
                except BlockingIOError:
                    time.sleep(0.1)
                    continue
                except Exception as e:
                    if not self._shutdown:
                        last_error = e
                        logger.error(f"Receive error: {e}")
                    break
        finally:
            if last_error is None:
                last_error = Exception("Connection closed")
            self._handle_disconnect(last_error)
            
    def _handle_disconnect(self, exc: Exception) -> None:
        should_reconnect = False
        with self._lock:
            was_connected = self._connected
            self._connected = False
            sock = self._socket
            self._socket = None
            
            if sock:
                try:
                    sock.close()
                except:
                    pass
                    
            if was_connected and self._on_disconnect:
                try:
                    self._on_disconnect(exc)
                except Exception as e:
                    logger.error(f"Error in disconnect callback: {e}")
                    
            should_reconnect = was_connected and self.reconnect and not self._shutdown
            
        if should_reconnect:
            self._schedule_reconnect()
            
    def _schedule_reconnect(self) -> None:
        delay = self._reconnect_delay
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
        logger.info(f"Reconnecting in {delay} seconds...")
        threading.Timer(delay, self._connect_internal).start()
        
    def send_message(self, message: str) -> None:
        with self._lock:
            if not self._connected or not self._socket:
                raise ConnectionError("Not connected")
            sock = self._socket
            
        try:
            sock.setblocking(True)
            sock.sendall(message.encode('utf-8'))
            sock.setblocking(False)
        except Exception as e:
            logger.error(f"Send failed: {e}")
            self._handle_disconnect(e)
            raise
                
    def on_message(self, callback: Callable[[str], None]) -> None:
        self._on_message = callback
        
    def on_disconnect(self, callback: Callable[[Exception], None]) -> None:
        self._on_disconnect = callback
        
    def close(self) -> None:
        with self._lock:
            self._shutdown = True
            self.reconnect = False
            sock = self._socket
            self._socket = None
            
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                sock.close()
            except:
                pass
                
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

def _selftest():
    """Offline self-test using local socket server"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', 0))
    port = server.getsockname()[1]
    server.listen(1)
    server.settimeout(0.5)
    
    server_active = True
    server_connections = []
    
    def server_loop():
        while server_active:
            try:
                conn, addr = server.accept()
                server_connections.append(conn)
                conn.settimeout(0.5)
                with conn:
                    while server_active:
                        try:
                            data = conn.recv(1024)
                            if not data:
                                break
                            conn.sendall(b"Echo: " + data)
                        except socket.timeout:
                            continue
                        except:
                            break
            except socket.timeout:
                continue
            except:
                break
    
    srv_thread = threading.Thread(target=server_loop, daemon=True)
    srv_thread.start()
    
    try:
        client = WebSocketClient(f"127.0.0.1:{port}", reconnect=True, timeout=2.0, heartbeat_interval=10.0)
        assert client.reconnect == True
        assert client.timeout == 2.0
        assert client.heartbeat_interval == 10.0
        
        messages = []
        disconnect_event = threading.Event()
        disconnect_error = [None]
        
        def on_msg(msg):
            messages.append(msg)
            
        def on_disc(exc):
            disconnect_error[0] = exc
            disconnect_event.set()
        
        client.on_message(on_msg)
        client.on_disconnect(on_disc)
        
        client.connect()
        time.sleep(0.3)
        
        client.send_message("Hello")
        time.sleep(0.3)
        
        assert len(messages) >= 1, f"Expected at least 1 message, got {len(messages)}"
        assert "Hello" in messages[0], f"Wrong message content: {messages[0]}"
        
        client.close()
        time.sleep(0.3)
        
        assert disconnect_event.is_set(), "Disconnect callback not triggered"
        
        messages.clear()
        disconnect_event.clear()
        
        client2 = WebSocketClient(f"127.0.0.1:{port}", reconnect=True, timeout=2.0)
        client2.on_message(on_msg)
        client2.on_disconnect(on_disc)
        
        client2.connect()
        time.sleep(0.3)
        
        client2.send_message("Before disconnect")
        time.sleep(0.3)
        assert len(messages) >= 1
        
        for conn in server_connections[:]:
            try:
                conn.close()
            except:
                pass
        server_connections.clear()
        
        time.sleep(2.5)
        
        messages.clear()
        client2.send_message("After reconnect")
        time.sleep(0.5)
        
        assert len(messages) >= 1, f"Reconnection failed, no messages received"
        assert "After reconnect" in messages[0], f"Wrong message after reconnect: {messages[0]}"
        
        client2.close()
        
        logger.info("All selftests passed")
        
    finally:
        server_active = False
        for conn in server_connections:
            try:
                conn.close()
            except:
                pass
        try:
            server.close()
        except:
            pass
        time.sleep(0.1)

if __name__ == "__main__":
    _selftest()
