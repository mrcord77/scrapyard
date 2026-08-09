"""
cache_client — Unified cache (memory | redis), fail-closed in production.

The in-memory backend is per-process: lost on restart and not shared across workers
or instances — fine for dev, forbidden in production (registered as a forbidden
fallback in runtime/fallbacks.py). Production sets CACHE_BACKEND=redis + REDIS_URL,
and a misconfigured/unreachable Redis fails fast at resolution time (ping) instead
of silently degrading to a local cache.

### PART-META-JSON
{
  "name": "cache_client",
  "layer": "caching",
  "purpose": "Unified cache (memory|redis); in-memory forbidden in production.",
  "addition": true,
  "status": "core",
  "dependencies": ["redis"],
  "inputs": "CACHE_BACKEND, REDIS_URL; key/value/ttl on the interface.",
  "outputs": "A cache with set/get/delete/clear; get_cache() resolves the backend.",
  "files_created": [],
  "security_notes": "Redis values are JSON-serialized. Namespaced keys; clear() is namespace-scoped (never FLUSHALL). In-memory backend refused in production.",
  "ai_usage": "from scrapyard.caching.cache_client import get_cache; c = get_cache()",
  "example": "from scrapyard.caching.cache_client import get_cache; get_cache().set('k', {'v':1}, ttl=60)",
  "import_path": "scrapyard.caching.cache_client"
}
### END-PART-META
"""
from __future__ import annotations
import os, time, json, threading

STATUS = "core"


class CacheClient:
    """In-memory TTL cache with the get/set/delete interface a Redis client matches.
    Per-process only — not for production (see get_cache / fallbacks)."""
    backend_name = "memory"

    def __init__(self):
        self._d = {}
        self._lock = threading.Lock()

    def set(self, key, value, ttl=None):
        with self._lock:
            self._d[key] = (value, time.time() + ttl if ttl else None)

    def get(self, key, default=None):
        with self._lock:
            item = self._d.get(key)
            if not item:
                return default
            value, exp = item
            if exp and exp < time.time():
                self._d.pop(key, None)
                return default
            return value

    def delete(self, key):
        with self._lock:
            return self._d.pop(key, None) is not None

    def clear(self):
        with self._lock:
            self._d.clear()

    def ping(self):
        return True


class RedisCache:
    """Real Redis-backed cache with the same interface. Values are JSON-serialized;
    keys are namespaced so clear() scopes to this app, never the whole server."""
    backend_name = "redis"

    def __init__(self, url, *, namespace="scrapyard"):
        import redis  # imported lazily so the memory path needs no redis installed
        self._r = redis.Redis.from_url(url, decode_responses=True)
        self._ns = namespace
        self._url = url

    def _k(self, key):
        return f"{self._ns}:{key}"

    def set(self, key, value, ttl=None):
        self._r.set(self._k(key), json.dumps(value), ex=ttl)

    def get(self, key, default=None):
        raw = self._r.get(self._k(key))
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw

    def delete(self, key):
        return self._r.delete(self._k(key)) > 0

    def clear(self):
        # namespace-scoped delete (never FLUSHALL)
        cursor = 0
        pattern = f"{self._ns}:*"
        while True:
            cursor, keys = self._r.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                self._r.delete(*keys)
            if cursor == 0:
                break

    def ttl(self, key):
        """Seconds remaining (-1 no expiry, -2 missing)."""
        return self._r.ttl(self._k(key))

    def ping(self):
        try:
            return bool(self._r.ping())
        except Exception:
            return False


def get_cache(namespace="scrapyard"):
    """Resolve the cache backend from the environment.
    CACHE_BACKEND=redis -> RedisCache (REDIS_URL); fails fast if Redis is unreachable.
    Anything else -> in-memory CacheClient (dev only; forbidden in production)."""
    backend = os.environ.get("CACHE_BACKEND", "memory").strip().lower()
    if backend == "redis":
        url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
        c = RedisCache(url, namespace=namespace)
        if not c.ping():
            raise RuntimeError(
                f"CACHE_BACKEND=redis but Redis is unreachable at {url} "
                "(start Redis or fix REDIS_URL); refusing to degrade to in-memory")
        return c
    return CacheClient()


# Back-compat default singleton (in-memory). Prefer get_cache() in app code.
client = CacheClient()


def _selftest() -> None:
    """Offline, falsifiable self-test of the in-memory cache backend (no Redis)."""
    c = CacheClient()

    # 1) set/get round-trips a structured value
    c.set("k1", {"v": 1})
    assert c.get("k1") == {"v": 1}, "set/get must round-trip"

    # 2) NEGATIVE: a missing key returns the provided default, not a stale/None hit
    sentinel = object()
    assert c.get("does-not-exist", sentinel) is sentinel, "miss must return the default"

    # 3) NEGATIVE: an expired entry is treated as a miss (ttl already in the past)
    c.set("k2", "value", ttl=-1)   # exp = now-1 => already expired
    assert c.get("k2", "DEFAULT") == "DEFAULT", "expired entry must not be returned"

    # 4) delete removes the key and reports whether something was removed
    c.set("k3", 99)
    assert c.delete("k3") is True and c.get("k3") is None, "delete must remove the key"
    assert c.delete("k3") is False, "deleting a missing key reports False"

    # 5) clear empties the namespace
    c.set("a", 1); c.set("b", 2); c.clear()
    assert c.get("a") is None and c.get("b") is None, "clear must empty the cache"

    # 6) get_cache() defaults to the in-memory backend when CACHE_BACKEND is unset
    saved = os.environ.pop("CACHE_BACKEND", None)
    try:
        assert isinstance(get_cache(), CacheClient), "default backend is in-memory"
    finally:
        if saved is not None:
            os.environ["CACHE_BACKEND"] = saved

    print("cache_client: OK (7 assertions incl. miss-default + ttl-expiry negatives)")


if __name__ == "__main__":
    _selftest()
