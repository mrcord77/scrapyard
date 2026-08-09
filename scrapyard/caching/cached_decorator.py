"""
cached_decorator — Memoize function results with TTL.

### PART-META-JSON
{
  "name": "cached_decorator",
  "layer": "caching",
  "purpose": "Memoize function results with TTL.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: serialize(value); deserialize(value); cache_key_from_args(fn, *a, key_prefix, version, **k); get_cached_value(key, client, default); set_cached_value(key, value, ttl, client) (plus more).",
  "outputs": "Returns: serialize -> str; deserialize -> Any; cache_key_from_args -> str; get_cached_value -> Any; set_cached_value -> None.",
  "files_created": [],
  "security_notes": "Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `serialize` from `scrapyard.caching.cached_decorator` and call it as shown in `example`; run `py -m scrapyard.caching.cached_decorator` to see its offline selftest.",
  "example": "from scrapyard.caching.cached_decorator import serialize",
  "import_path": "scrapyard.caching.cached_decorator"
}
### END-PART-META
"""
from __future__ import annotations

import functools
import hashlib
import json
from typing import Any, Callable, Optional

STATUS = "core"

_MISS = object()


def _client(client=None):
    if client is not None:
        return client
    from scrapyard.caching.cache_client import client as default
    return default


def serialize(value: Any) -> str:
    return json.dumps(value, default=str)


def deserialize(value: str) -> Any:
    return json.loads(value)


def cache_key_from_args(fn: Callable, *a, key_prefix: Optional[str] = None,
                        version: int = 0, **k) -> str:
    raw = serialize([fn.__name__, a, sorted(k.items()), version])
    prefix = f"{key_prefix}:" if key_prefix else ""
    return f"cache:{prefix}{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def get_cached_value(key: str, client=None, default: Any = None) -> Any:
    hit = _client(client).get(key, _MISS)
    return default if hit is _MISS else hit


def set_cached_value(key: str, value: Any, ttl: int, client=None) -> None:
    _client(client).set(key, value, ttl)


def delete_cached_value(key: str, client=None) -> None:
    c = _client(client)
    if hasattr(c, "delete"):
        c.delete(key)
    else:
        c.set(key, None, 0)


def cached(ttl=60, client=None, key_prefix: Optional[str] = None,
           version: int = 0, cache_none: bool = False):
    """Memoize a function's result in the cache for ttl seconds, keyed by args.

    version bumps invalidate old entries; cache_none controls whether a None
    result is stored (default: recompute on None)."""

    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a, **k):
            c = _client(client)
            key = cache_key_from_args(fn, *a, key_prefix=key_prefix,
                                      version=version, **k)
            hit = c.get(key, _MISS)
            if hit is not _MISS:
                return hit
            val = fn(*a, **k)
            if val is not None or cache_none:
                c.set(key, val, ttl)
            return val

        wrap.cache_key = lambda *a, **k: cache_key_from_args(  # type: ignore[attr-defined]
            fn, *a, key_prefix=key_prefix, version=version, **k)
        return wrap

    return deco


def invalidate(fn_wrapped: Callable, *a, client=None, **k) -> None:
    """Invalidate the cached entry for a @cached function + specific args."""
    key_builder = getattr(fn_wrapped, "cache_key", None)
    if key_builder is None:
        raise TypeError("invalidate() requires a function wrapped by @cached")
    delete_cached_value(key_builder(*a, **k), client=client)


def _selftest() -> None:
    """Offline, falsifiable self-test of the @cached memoization decorator."""
    from scrapyard.caching.cache_client import CacheClient
    cache = CacheClient()
    calls = {"n": 0}

    @cached(ttl=60, client=cache)
    def square(x):
        calls["n"] += 1
        return x * x

    # 1) first call computes; identical args are served from cache (no recompute)
    assert square(5) == 25, "correct result"
    assert square(5) == 25, "cached result"
    assert calls["n"] == 1, "second identical call must be a cache hit (computed once)"

    # 2) NEGATIVE: different args are a distinct key -> recompute
    assert square(6) == 36
    assert calls["n"] == 2, "different args must miss the cache and recompute"

    # 3) invalidate() forces the next call to recompute
    invalidate(square, 5, client=cache)
    assert square(5) == 25
    assert calls["n"] == 3, "after invalidate the entry must be recomputed"

    # 4) NEGATIVE: distinct arguments produce distinct cache keys
    k5 = cache_key_from_args(square.__wrapped__, 5)
    k6 = cache_key_from_args(square.__wrapped__, 6)
    assert k5 != k6, "different args must yield different cache keys"

    # 5) get/set/delete helpers operate against the same cache
    set_cached_value("manual", [1, 2, 3], ttl=60, client=cache)
    assert get_cached_value("manual", client=cache) == [1, 2, 3]
    delete_cached_value("manual", client=cache)
    assert get_cached_value("manual", client=cache, default="GONE") == "GONE"

    print("cached_decorator: OK (7 assertions incl. distinct-key + post-invalidate recompute)")


if __name__ == "__main__":
    _selftest()
