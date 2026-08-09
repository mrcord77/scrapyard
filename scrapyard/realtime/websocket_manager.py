"""
websocket_manager — Track + broadcast over WebSocket connections.

### PART-META-JSON
{
  "name": "websocket_manager",
  "layer": "realtime",
  "purpose": "Track + broadcast over WebSocket connections.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Public API: UserConnection(...); ConnectionManager(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `UserConnection` from `scrapyard.realtime.websocket_manager` and call it as shown in `example`; run `py -m scrapyard.realtime.websocket_manager` to see its offline selftest.",
  "example": "from scrapyard.realtime.websocket_manager import UserConnection",
  "import_path": "scrapyard.realtime.websocket_manager"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
from typing import Any, Dict, List, Optional, TypeVar, Callable
import inspect
from fastapi import WebSocket

T = TypeVar('T')

class UserConnection:
    def __init__(self, user_id: str, conn: WebSocket):
        self.user_id = user_id
        self.conn = conn

class ConnectionManager:
    """Track websocket connections by channel and broadcast to them. Transport-
    agnostic: connections just need an async send()/a .send sink; tested with fakes."""
    def __init__(self): 
        self.channels = {}  # channel -> set(conn)
        self.users = {}  # user_id -> set(conn)
        self.channels_by_user = {}  # user_id -> List[str]
        self.redis_client = None
        self._event_callbacks: List[Callable[[str, str, Any], Any]] = []
    
    def connect(self, channel: str, conn):
        self.channels.setdefault(channel, set()).add(conn)
    
    def disconnect(self, channel: str, conn):
        self.channels.get(channel, set()).discard(conn)
    
    def members(self, channel: str) -> int:
        return len(self.channels.get(channel, set()))
    
    async def broadcast(self, channel: str, message) -> int:
        sent = 0
        for conn in list(self.channels.get(channel, set())):
            await conn.send(message); sent += 1
        return sent
    
    def broadcast_sync(self, channel: str, message) -> int:
        sent = 0
        for conn in list(self.channels.get(channel, set())):
            conn.send(message); sent += 1
        return sent
    
    async def configure(self, backend: str = "in-memory", redis_url: str = "redis://localhost:6379"):
        if backend == "redis":
            from redis import Redis
            self.redis_client = Redis.from_url(redis_url)
    
    async def add_connection(self, channel: str, conn: WebSocket, user_id: Optional[str] = None):
        self.channels.setdefault(channel, set()).add(conn)
        if user_id:
            self.users.setdefault(user_id, set()).add(conn)
            self.channels_by_user.setdefault(user_id, []).append(channel)
            await self.log_connection_event("connected", user_id, channel)
    
    async def remove_connection(self, channel: str, conn: WebSocket, user_id: Optional[str] = None):
        if user_id:
            self.users[user_id].discard(conn)
            for ch in self.channels_by_user.get(user_id, []):
                self.channels.get(ch, set()).discard(conn)
            await self.log_connection_event("disconnected", user_id, channel)
    
    def get_connections(self, channel: str, user_id: Optional[str] = None) -> List[WebSocket]:
        if user_id:
            return [c for c in self.users.get(user_id, [])]
        else:
            return list(self.channels.get(channel, set()))
    
    async def broadcast_to(self, channel: str, message: Any, user_id: Optional[str] = None, exclude_user: Optional[str] = None):
        sent = 0
        if user_id and exclude_user:
            for conn in self.users.get(user_id, []):
                if conn.user_id != exclude_user:
                    await conn.send(message)
                    sent += 1
        elif user_id:
            for conn in self.users.get(user_id, []):
                await conn.send(message)
                sent += 1
        else:
            for conn in list(self.channels.get(channel, set())):
                await conn.send(message)
                sent += 1
        return sent
    
    async def broadcast_to_all(self, message: Any, user_id: Optional[str] = None, exclude_user: Optional[str] = None):
        total_sent = 0
        if user_id and exclude_user:
            for user_conns in self.users.values():
                for conn in user_conns:
                    if conn.user_id != exclude_user:
                        await conn.send(message)
                        total_sent += 1
        elif user_id:
            for user_conns in self.users.values():
                for conn in user_conns:
                    await conn.send(message)
                    total_sent += 1
        else:
            for channel, conns in self.channels.items():
                total_sent += await self.broadcast(channel, message)
        return total_sent
    
    def subscribe_user(self, user_id: str, channels: List[str]):
        self.channels_by_user.setdefault(user_id, []).extend(channels)
    
    def unsubscribe_user(self, user_id: str, channels: List[str]):
        if user_id in self.channels_by_user:
            for ch in channels:
                self.channels.get(ch, set()).discard([c for c in self.users.get(user_id, [])])
            del self.channels_by_user[user_id]
    
    def get_subscribed_channels(self, user_id: str) -> List[str]:
        return self.channels_by_user.get(user_id, [])
    
    async def send_message_to_user(self, user_id: str, message: Any):
        for conn in self.users.get(user_id, []):
            await conn.send(message)
    
    async def log_connection_event(self, event_type: str, user_id: Optional[str],
                                   channel: Optional[str], message: Optional[Any] = None):
        if self.redis_client:
            data = {"event_type": event_type, "user_id": user_id, "channel": channel, "message": message}
            result = self.redis_client.xadd("connection_events", data)
            if inspect.isawaitable(result):
                await result
        for callback in tuple(self._event_callbacks):
            result = callback(event_type, user_id, {"channel": channel, "message": message})
            if inspect.isawaitable(result):
                await result
    
    def get_connection_count(self, channel: str) -> int:
        return len(self.channels.get(channel, set()))
    
    def get_user_connection_count(self, user_id: str) -> int:
        return len(self.users.get(user_id, []))
    
    async def get_all_connections(self) -> Dict[str, List[WebSocket]]:
        all_conns = {}
        for channel, conns in self.channels.items():
            all_conns[channel] = [c.conn for c in conns]
        return all_conns
    
    async def get_all_users(self) -> List[str]:
        return list(self.users.keys())
    
    def on_connection_event(self, callback: Callable[[str, str, Any], None]):
        if not callable(callback):
            raise TypeError("connection event callback must be callable")
        if callback not in self._event_callbacks:
            self._event_callbacks.append(callback)
        return callback


def _selftest() -> None:
    """Offline self-test: track + broadcast + disconnect with fake transports."""
    import asyncio

    class FakeConn:
        """Stand-in for a WebSocket: records everything sent to it."""
        def __init__(self, user_id: str = "u"):
            self.user_id = user_id
            self.received: list = []

        async def send(self, message):
            self.received.append(message)

    async def scenario():
        mgr = ConnectionManager()
        a, b = FakeConn("a"), FakeConn("b")
        events = []
        mgr.on_connection_event(lambda event, user, data: events.append((event, user, data)))
        await mgr.add_connection("events", a, "a")
        await mgr.remove_connection("events", a, "a")
        assert [event[0] for event in events] == ["connected", "disconnected"]

        # connect + track
        mgr.connect("room1", a)
        mgr.connect("room1", b)
        assert mgr.members("room1") == 2, "both connections must be tracked"

        # broadcast reaches every subscriber
        sent = await mgr.broadcast("room1", "hello")
        assert sent == 2, "broadcast must report every recipient"
        assert a.received == ["hello"] and b.received == ["hello"]

        # disconnect one, then broadcast again
        mgr.disconnect("room1", b)
        assert mgr.members("room1") == 1
        sent = await mgr.broadcast("room1", "second")
        assert sent == 1, "only the still-connected subscriber receives"
        # positive: remaining subscriber got the new message
        assert a.received == ["hello", "second"]
        # negative: the disconnected subscriber did NOT receive it
        assert b.received == ["hello"], "unsubscribed connection must not receive"

        # negative: broadcasting to an unknown channel reaches nobody
        assert await mgr.broadcast("no-such-room", "x") == 0

    asyncio.run(scenario())
    print("websocket_manager self-test passed")


if __name__ == "__main__":
    _selftest()
