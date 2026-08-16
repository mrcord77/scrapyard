"""
rate_limiting — Token-bucket rate limiter (in-mem/redis).

### PART-META-JSON
{
  "name": "rate_limiting",
  "layer": "security",
  "purpose": "Token-bucket rate limiter (in-mem/redis).",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: get_rate_limiter(capacity, refill_per_sec, namespace); TokenBucket(...); RateLimiter(...); RedisRateLimiter(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "The in-memory backend is process-local and is rejected when APP_ENV or ENVIRONMENT is production. Redis uses an atomic Lua token bucket and fails fast when selected but unreachable. Keys may contain user/IP identifiers; avoid raw sensitive values and choose a bounded namespace.",
  "ai_usage": "Import `get_rate_limiter` from `scrapyard.security.rate_limiting` and call it as shown in `example`; run `py -m scrapyard.security.rate_limiting` to see its offline selftest.",
  "example": "from scrapyard.security.rate_limiting import get_rate_limiter",
  "import_path": "scrapyard.security.rate_limiting"
}
### END-PART-META
"""
from __future__ import annotations
import os
import threading
import time

STATUS = "core"


class TokenBucket:
    """Thread-safe token bucket: ``capacity`` tokens, refilled ``refill_per_sec``."""
    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = capacity
        self.refill = refill_per_sec
        self._tokens = float(capacity)
        self._ts = time.monotonic()
        self._lock = threading.Lock()

    def allow(self, cost: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self.capacity, self._tokens + (now - self._ts) * self.refill)
            self._ts = now
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False


class RateLimiter:
    """Per-key token buckets (per IP or per user). In-memory; swap for a
    redis-backed store in multi-process deployments."""
    def __init__(self, capacity: int = 60, refill_per_sec: float = 1.0) -> None:
        self._cap = capacity
        self._refill = refill_per_sec
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: float = 1.0) -> bool:
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = self._buckets[key] = TokenBucket(self._cap, self._refill)
        return b.allow(cost)


# --- Distributed (Redis) rate limiter -------------------------------------------
# The in-memory limiter keeps state per process, so N instances each admit the full
# limit => effectively N x the intended rate. This limiter holds the token bucket in
# Redis and checks/decrements it ATOMICALLY in a single Lua script, so the limit is
# enforced GLOBALLY across all instances and is safe under concurrency.

_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
local d = redis.call('HMGET', key, 't', 'ts')
local tokens = tonumber(d[1])
local ts = tonumber(d[2])
if tokens == nil then tokens = capacity; ts = now end
local delta = now - ts
if delta < 0 then delta = 0 end
tokens = math.min(capacity, tokens + delta * refill)
local allowed = 0
if tokens >= cost then tokens = tokens - cost; allowed = 1 end
redis.call('HSET', key, 't', tokens, 'ts', now)
redis.call('PEXPIRE', key, ttl)
return allowed
""".strip()


class RedisRateLimiter:
    """Per-key token bucket whose state lives in Redis; the check-and-decrement is a
    single atomic Lua EVAL, so the limit holds across every instance and worker.
    Same interface as RateLimiter: allow(key, cost=1.0) -> bool."""
    backend_name = "redis"

    def __init__(self, url, capacity: int = 60, refill_per_sec: float = 1.0,
                 namespace: str = "rl"):
        import redis
        self._redis = redis
        self._r = redis.Redis.from_url(url)
        self._cap = capacity
        self._refill = refill_per_sec
        self._ns = namespace
        self._sha = None
        self._ttl_ms = int((capacity / refill_per_sec) * 2 * 1000) if refill_per_sec > 0 else 60000

    def _sha1(self):
        if self._sha is None:
            self._sha = self._r.script_load(_BUCKET_LUA)
        return self._sha

    def allow(self, key: str, cost: float = 1.0) -> bool:
        now = time.time()
        args = (1, f"{self._ns}:{key}", self._cap, self._refill, now, cost, self._ttl_ms)
        try:
            res = self._r.evalsha(self._sha1(), *args)
        except self._redis.exceptions.NoScriptError:
            self._sha = None
            res = self._r.eval(_BUCKET_LUA, *args)
        return bool(res)

    def ping(self) -> bool:
        try:
            return bool(self._r.ping())
        except Exception:
            return False


def get_rate_limiter(capacity: int = 60, refill_per_sec: float = 1.0, namespace: str = "rl"):
    """Resolve the limiter backend from the environment.
    RATE_LIMIT_BACKEND=redis -> RedisRateLimiter (REDIS_URL), fails fast if unreachable.
    Anything else -> in-memory RateLimiter (development only; rejected in production)."""
    backend = os.environ.get("RATE_LIMIT_BACKEND", "memory").strip().lower()
    if backend == "redis":
        url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
        rl = RedisRateLimiter(url, capacity, refill_per_sec, namespace)
        if not rl.ping():
            raise RuntimeError(
                f"RATE_LIMIT_BACKEND=redis but Redis is unreachable at {url}; "
                "refusing to degrade to per-instance limiting")
        return rl
    environment = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development"))
    if environment.strip().lower() == "production":
        raise RuntimeError(
            "the in-memory rate limiter is process-local and forbidden in production; "
            "set RATE_LIMIT_BACKEND=redis and REDIS_URL"
        )
    return RateLimiter(capacity, refill_per_sec)


def _selftest() -> None:
    """Offline, falsifiable self-test of the in-memory token bucket (no Redis)."""
    # 1) a bucket admits exactly `capacity` requests, then blocks the N+1th.
    #    refill=0 so nothing replenishes during the test (deterministic).
    bucket = TokenBucket(capacity=3, refill_per_sec=0.0)
    assert [bucket.allow() for _ in range(3)] == [True, True, True], "first N must pass"
    # NEGATIVE: the N+1th call in the window is blocked
    assert bucket.allow() is False, "the (N+1)th request must be blocked"

    # 2) refill restores capacity: a full bucket refilled at 1000/s admits again
    b2 = TokenBucket(capacity=1, refill_per_sec=1000.0)
    assert b2.allow() is True, "first token available"
    assert b2.allow() is False, "immediately empty"
    time.sleep(0.02)  # ~20 tokens worth of refill at 1000/s
    assert b2.allow() is True, "refill must restore availability"

    # 3) per-key isolation: exhausting one key does not block another
    rl = RateLimiter(capacity=2, refill_per_sec=0.0)
    assert rl.allow("ip-A") and rl.allow("ip-A"), "key A gets its full budget"
    assert rl.allow("ip-A") is False, "key A is now exhausted"
    assert rl.allow("ip-B") is True, "key B has an independent budget"

    # 4) cost>1 consumes multiple tokens at once
    b3 = TokenBucket(capacity=5, refill_per_sec=0.0)
    assert b3.allow(cost=5) is True and b3.allow(cost=1) is False, "cost accounting works"

    # 5) a production process cannot silently use per-process state.
    saved_env = os.environ.get("APP_ENV")
    saved_backend = os.environ.get("RATE_LIMIT_BACKEND")
    try:
        os.environ["APP_ENV"] = "production"
        os.environ["RATE_LIMIT_BACKEND"] = "memory"
        try:
            get_rate_limiter()
            raise AssertionError("production accepted the in-memory backend")
        except RuntimeError as exc:
            assert "forbidden in production" in str(exc)
    finally:
        if saved_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = saved_env
        if saved_backend is None:
            os.environ.pop("RATE_LIMIT_BACKEND", None)
        else:
            os.environ["RATE_LIMIT_BACKEND"] = saved_backend

    print("rate_limiting: OK (7 assertions incl. N+1 blocked + exhaustion negatives)")


if __name__ == "__main__":
    _selftest()
