"""
account_lockout — Lock accounts after repeated failed logins.

### PART-META-JSON
{
  "name": "account_lockout",
  "layer": "identity",
  "purpose": "Failed-login lockout: per-identifier failure counting with configurable threshold and lock window, in-memory store for single-process use, Redis-backed store (injectable client) for shared state, lockout events, hooks, and bulk operations.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Account identifiers (username/email/IP) plus failure/success signals from the auth flow.",
  "outputs": "Lock decisions (bool), LockStatus/LockResult/LockoutStats records, LockEvent streams.",
  "files_created": [],
  "security_notes": "Lockout keys are attacker-controlled identifiers; keying by username alone enables denial-of-service against a victim account, so consider compound keys (user+IP). In-memory stores do not share state across processes; use RedisStore with a shared client for multi-instance deployments. Redis values are decoded defensively (bytes vs str). No passwords or secrets are ever stored, only counters and timestamps. The redis client library is imported lazily and only needed if RedisStore is constructed without an injected client.",
  "ai_usage": "Construct AccountLockout() (or a LockoutStore) at app startup; call is_locked() before verifying credentials, record_failure()/record_success() after.",
  "example": "lock = AccountLockout(threshold=5, lock_seconds=900); if lock.is_locked(user): reject(); elif bad_password: lock.record_failure(user)",
  "import_path": "scrapyard.identity.account_lockout"
}
### END-PART-META
"""
from __future__ import annotations

import abc
import time
from typing import Any, Callable, Optional

STATUS = "core"


class AccountLockout:
    """In-memory failed-attempt tracker. Locks an identifier after `threshold`
    failures for `lock_seconds`. Swap the store for Redis in production."""
    def __init__(self, threshold: int = 5, lock_seconds: int = 900):
        self.threshold = threshold; self.lock_seconds = lock_seconds
        self._fails: dict[str, list] = {}
        self._locked: dict[str, float] = {}
    def is_locked(self, key: str) -> bool:
        until = self._locked.get(key)
        if until and until > time.time():
            return True
        if until:
            self._locked.pop(key, None); self._fails.pop(key, None)
        return False
    def record_failure(self, key: str) -> bool:
        self._fails.setdefault(key, []).append(time.time())
        if len(self._fails[key]) >= self.threshold:
            self._locked[key] = time.time() + self.lock_seconds
            return True
        return False
    def record_success(self, key: str):
        self._fails.pop(key, None); self._locked.pop(key, None)


class LockPolicy:
    def __init__(self, threshold: int, lock_seconds: int):
        self.threshold = threshold
        self.lock_seconds = lock_seconds

class LockStatus:
    def __init__(self, locked_until: float, failure_count: int):
        self.locked_until = locked_until
        self.failure_count = failure_count

class LockResult:
    def __init__(self, key: str, success: bool, status: LockStatus):
        self.key = key
        self.success = success
        self.status = status

class LockEvent:
    def __init__(self, key: str, event_type: str, timestamp: float):
        self.key = key
        self.event_type = event_type
        self.timestamp = timestamp

class LockoutStats:
    def __init__(self, total_failures: int, lockouts: int):
        self.total_failures = total_failures
        self.lockouts = lockouts


class LockoutStore(abc.ABC):
    @abc.abstractmethod
    def record_failure(self, key: str) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def is_locked(self, key: str) -> bool:
        raise NotImplementedError()

    @abc.abstractmethod
    def reset_lock(self, key: str) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def get_status(self, key: str) -> LockStatus:
        raise NotImplementedError()


class InMemoryStore(LockoutStore):
    def __init__(self, threshold: int = 5, lock_seconds: int = 900):
        self.threshold = threshold
        self.lock_seconds = lock_seconds
        self._fails: dict[str, list] = {}
        self._locked: dict[str, float] = {}

    def record_failure(self, key: str) -> None:
        self._fails.setdefault(key, []).append(time.time())
        if len(self._fails[key]) >= self.threshold:
            self._locked[key] = time.time() + self.lock_seconds

    def is_locked(self, key: str) -> bool:
        until = self._locked.get(key)
        if until and until > time.time():
            return True
        if until:
            self._locked.pop(key, None); self._fails.pop(key, None)
        return False

    def reset_lock(self, key: str) -> None:
        self._fails.pop(key, None); self._locked.pop(key, None)

    def get_status(self, key: str) -> LockStatus:
        failures = self._fails.get(key, [])
        locked_until = self._locked.get(key, 0.0)
        if locked_until and locked_until <= time.time():
            locked_until = 0.0
        return LockStatus(locked_until=locked_until, failure_count=len(failures))


class RedisStore(LockoutStore):
    """Redis-backed lockout store. Failure counts live in per-key counters
    (``lockout:fails:<key>``) with a rolling expiry; locks are TTL keys
    (``lockout:lock:<key>``). A pre-built client (or any object with the same
    get/set/incr/expire/ttl/delete interface) can be injected for testing —
    only when ``client`` is None is the redis library imported and a real
    connection configured."""

    FAIL_PREFIX = "lockout:fails:"
    LOCK_PREFIX = "lockout:lock:"

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0,
                 threshold: int = 5, lock_seconds: int = 900,
                 client: Optional[Any] = None):
        self.threshold = threshold
        self.lock_seconds = lock_seconds
        self._enabled = True
        self._events: list[LockEvent] = []
        self._on_lockout: list[Callable[[str, LockEvent], None]] = []
        self._on_unlock: list[Callable[[str, LockEvent], None]] = []
        if client is not None:
            self.client = client
        else:
            import redis
            self.client = redis.Redis(host=host, port=port, db=db)

    @staticmethod
    def _to_str(value: Any) -> Optional[str]:
        """redis-py returns bytes by default; normalise to str for comparison."""
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        s = RedisStore._to_str(value)
        try:
            return int(s) if s is not None else default
        except ValueError:
            return default

    def record_failure(self, key: str) -> None:
        if not self._enabled:
            return
        fail_key = self.FAIL_PREFIX + key
        count = self._to_int(self.client.incr(fail_key))
        self.client.expire(fail_key, self.lock_seconds)
        event = LockEvent(key=key, event_type="failure", timestamp=time.time())
        self._events.append(event)
        if count >= self.threshold:
            self.client.setex(self.LOCK_PREFIX + key, self.lock_seconds, "locked")
            lock_event = LockEvent(key=key, event_type="lockout", timestamp=time.time())
            self._events.append(lock_event)
            for hook in self._on_lockout:
                hook(key, lock_event)

    def is_locked(self, key: str) -> bool:
        if not self._enabled:
            return False
        return self._to_str(self.client.get(self.LOCK_PREFIX + key)) == "locked"

    def reset_lock(self, key: str) -> None:
        self.client.delete(self.LOCK_PREFIX + key)
        self.client.delete(self.FAIL_PREFIX + key)
        event = LockEvent(key=key, event_type="unlock", timestamp=time.time())
        self._events.append(event)
        for hook in self._on_unlock:
            hook(key, event)

    def get_status(self, key: str) -> LockStatus:
        failures = self._to_int(self.client.get(self.FAIL_PREFIX + key))
        locked_until = 0.0
        if self.is_locked(key):
            ttl = self._to_int(self.client.ttl(self.LOCK_PREFIX + key), default=-1)
            locked_until = time.time() + max(ttl, 0)
        return LockStatus(locked_until=locked_until, failure_count=failures)

    def get_lock_policy(self) -> LockPolicy:
        return LockPolicy(threshold=self.threshold, lock_seconds=self.lock_seconds)

    def set_lock_policy(self, policy: LockPolicy) -> None:
        self.threshold = policy.threshold
        self.lock_seconds = policy.lock_seconds

    def is_lockout_enabled(self) -> bool:
        return self._enabled

    def enable_lockout(self, enable: bool) -> None:
        """Enable/disable enforcement; when disabled, is_locked always False
        and failures are not recorded."""
        self._enabled = bool(enable)

    def get_lockout_events(self) -> list[LockEvent]:
        return list(self._events)

    def clear_lockout_events(self) -> None:
        self._events.clear()

    def get_lockout_statistics(self) -> LockoutStats:
        total_failures = sum(1 for e in self._events if e.event_type == "failure")
        lockouts = sum(1 for e in self._events if e.event_type == "lockout")
        return LockoutStats(total_failures=total_failures, lockouts=lockouts)

    def bulk_record_failures(self, keys: list[str]) -> list[LockResult]:
        results = []
        for key in keys:
            self.record_failure(key)
            status = self.get_status(key)
            results.append(LockResult(key=key, success=status.locked_until > 0, status=status))
        return results

    def bulk_reset_locks(self, keys: list[str]) -> None:
        for key in keys:
            self.reset_lock(key)

    def on_lockout_hook(self, func: Callable[[str, LockEvent], None]) -> None:
        """Register a callback fired when a key crosses the lockout threshold."""
        if not callable(func):
            raise TypeError("hook must be callable")
        self._on_lockout.append(func)

    def on_unlock_hook(self, func: Callable[[str, LockEvent], None]) -> None:
        """Register a callback fired when a key's lock is reset."""
        if not callable(func):
            raise TypeError("hook must be callable")
        self._on_unlock.append(func)

    def serialize_state(self) -> dict[str, Any]:
        """Serialize the store's local (non-Redis) state: policy + events."""
        return {
            "threshold": self.threshold,
            "lock_seconds": self.lock_seconds,
            "enabled": self._enabled,
            "events": [(e.key, e.event_type, e.timestamp) for e in self._events],
        }

    def deserialize_state(self, state: dict[str, Any]) -> None:
        self.threshold = int(state["threshold"])
        self.lock_seconds = int(state["lock_seconds"])
        self._enabled = bool(state.get("enabled", True))
        self._events = [LockEvent(key=k, event_type=t, timestamp=ts)
                        for (k, t, ts) in state.get("events", [])]


class _FakeRedis:
    """Minimal offline stand-in mimicking redis-py semantics (returns BYTES)."""
    def __init__(self):
        self.data: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
    def incr(self, key):
        val = int(self.data.get(key, b"0")) + 1
        self.data[key] = str(val).encode()
        return val
    def expire(self, key, seconds):
        self.ttls[key] = seconds
        return True
    def setex(self, key, seconds, value):
        self.data[key] = value.encode() if isinstance(value, str) else value
        self.ttls[key] = seconds
        return True
    def get(self, key):
        return self.data.get(key)
    def ttl(self, key):
        return self.ttls.get(key, -2)
    def delete(self, key):
        self.data.pop(key, None); self.ttls.pop(key, None)


def _selftest() -> None:
    # --- AccountLockout (primary in-memory tracker) ---
    lock = AccountLockout(threshold=3, lock_seconds=60)
    assert not lock.is_locked("alice")
    assert lock.record_failure("alice") is False
    assert lock.record_failure("alice") is False
    assert lock.record_failure("alice") is True  # third strike locks
    assert lock.is_locked("alice")
    lock.record_success("bob")  # unknown key is a no-op
    lock.record_success("alice")
    assert not lock.is_locked("alice")
    # lock expiry
    fast = AccountLockout(threshold=1, lock_seconds=0)
    fast.record_failure("carol")
    assert not fast.is_locked("carol")  # 0-second lock already expired

    # --- InMemoryStore (threshold/lock_seconds now set in __init__) ---
    store = InMemoryStore(threshold=2, lock_seconds=60)
    store.record_failure("dave")
    st = store.get_status("dave")  # used to AttributeError on self.threshold
    assert st.failure_count == 1 and st.locked_until == 0.0
    assert not store.is_locked("dave")
    store.record_failure("dave")
    assert store.is_locked("dave")
    assert store.get_status("dave").locked_until > time.time()
    store.reset_lock("dave")
    assert not store.is_locked("dave")
    assert store.get_status("dave").failure_count == 0

    # --- RedisStore against an injected fake client (offline; bytes semantics) ---
    rs = RedisStore(threshold=2, lock_seconds=30, client=_FakeRedis())
    locked_events: list[str] = []
    unlocked_events: list[str] = []
    rs.on_lockout_hook(lambda k, e: locked_events.append(k))
    rs.on_unlock_hook(lambda k, e: unlocked_events.append(k))
    assert not rs.is_locked("eve")
    rs.record_failure("eve")
    assert not rs.is_locked("eve")
    rs.record_failure("eve")
    # bytes-vs-str comparison bug would make this False forever:
    assert rs.is_locked("eve") is True
    assert locked_events == ["eve"]
    st = rs.get_status("eve")
    assert st.failure_count == 2 and st.locked_until > time.time()
    rs.reset_lock("eve")
    assert not rs.is_locked("eve")
    assert unlocked_events == ["eve"]

    # policy, enable/disable, events, stats
    rs.set_lock_policy(LockPolicy(threshold=1, lock_seconds=10))
    assert rs.get_lock_policy().threshold == 1
    rs.enable_lockout(False)
    rs.record_failure("frank")
    assert not rs.is_locked("frank")
    rs.enable_lockout(True)
    rs.record_failure("frank")
    assert rs.is_locked("frank")
    stats = rs.get_lockout_statistics()
    assert stats.total_failures >= 3 and stats.lockouts >= 2
    assert any(e.event_type == "lockout" for e in rs.get_lockout_events())
    rs.clear_lockout_events()
    assert rs.get_lockout_events() == []

    # bulk ops + state round-trip
    results = rs.bulk_record_failures(["g1", "g2"])
    assert len(results) == 2 and all(r.success for r in results)  # threshold=1
    rs.bulk_reset_locks(["g1", "g2"])
    assert not rs.is_locked("g1") and not rs.is_locked("g2")
    blob = rs.serialize_state()
    rs2 = RedisStore(client=_FakeRedis())
    rs2.deserialize_state(blob)
    assert rs2.threshold == 1 and rs2.lock_seconds == 10

    print("account_lockout selftest: PASS")


if __name__ == "__main__":
    _selftest()
