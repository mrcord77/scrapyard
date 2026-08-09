"""
cache_invalidation — Tag-based invalidation helpers.

### PART-META-JSON
{
  "name": "cache_invalidation",
  "layer": "caching",
  "purpose": "Tag-based cache invalidation over a redis-compatible client: tag keys, invalidate by key/prefix/tag, JSON metadata, and in-process tag subscriptions.",
  "addition": true,
  "status": "core",
  "dependencies": ["redis"],
  "inputs": "A redis-compatible client (real redis.Redis or any object with get/set/delete/keys), keys, tags, namespaces.",
  "outputs": "Invalidation counts; tag/key listings; metadata dicts; callback firings on tag invalidation.",
  "files_created": [],
  "security_notes": "Metadata is parsed with json.loads only - never eval. Concurrency uses this module's own threading.Lock, not the client's private internals. Selftest runs against an in-memory fake client (no live Redis needed); pass a real redis.Redis in production.",
  "ai_usage": "add_tag_to_key(client, key, tag); invalidate_by_tag(client, tag) later. subscribe_to_tag(client, tag, cb) to get callbacks when tagged keys are invalidated (in-process registry, not redis pubsub).",
  "example": "from scrapyard.caching.cache_invalidation import add_tag_to_key, invalidate_by_tag",
  "import_path": "scrapyard.caching.cache_invalidation"
}
### END-PART-META
"""
from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Callable, Dict, List

from pydantic import BaseModel

STATUS = "core"

# Module-owned lock for scan+mutate sequences (never touch client internals).
_lock = threading.Lock()

# In-process subscription registry: subscription_id -> (namespace, tag, callback)
_subscriptions: Dict[str, tuple] = {}


class CacheInvalidationError(Exception):
    pass


class CacheTaggingModel(BaseModel):
    tag: str
    namespace: str = "default"


def _decode(k: Any) -> str:
    return k.decode() if isinstance(k, (bytes, bytearray)) else str(k)


def _notify_subscribers(namespace: str, tag: str, key: str) -> None:
    for _, (ns, t, cb) in list(_subscriptions.items()):
        if ns == namespace and t == tag:
            try:
                cb(key)
            except Exception:
                pass  # a subscriber must not break invalidation


def invalidate(client, *keys: str) -> int:
    return sum(1 for k in keys if client.delete(k))


def invalidate_prefix(client, prefix: str) -> int:
    with _lock:
        keys = [_decode(k) for k in client.keys(f"{prefix}*")]
        return invalidate(client, *keys)


def invalidate_by_tag(client, tag: str, namespace: str = "default") -> int:
    pattern = f"tag:{namespace}:{tag}:*"
    with _lock:
        tag_keys = [_decode(k) for k in client.keys(pattern)]
        count = 0
        for tk in tag_keys:
            data_key = tk.split(":", 3)[-1]
            client.delete(data_key)   # the cached value itself
            client.delete(tk)         # the tag marker
            _notify_subscribers(namespace, tag, data_key)
            count += 1
        return count


def invalidate_by_prefix_and_tag(client, prefix: str, tag: str,
                                 namespace: str = "default") -> int:
    pattern = f"tag:{namespace}:{tag}:*"
    with _lock:
        tag_keys = [_decode(k) for k in client.keys(pattern)]
        count = 0
        for tk in tag_keys:
            data_key = tk.split(":", 3)[-1]
            if data_key.startswith(prefix):
                client.delete(data_key)
                client.delete(tk)
                _notify_subscribers(namespace, tag, data_key)
                count += 1
        return count


def bulk_invalidate(client, keys: List[str]) -> int:
    invalidated = 0
    for key in keys:
        try:
            if client.delete(key):
                invalidated += 1
        except Exception as e:
            raise CacheInvalidationError(f"Error invalidating key {key}: {e}")
    return invalidated


def invalidate_all(client, namespace: str = "default") -> int:
    pattern = f"tag:{namespace}:*"
    with _lock:
        tag_keys = [_decode(k) for k in client.keys(pattern)]
        keys = [tk.split(":", 3)[-1] for tk in tag_keys if len(tk.split(":", 3)) == 4]
        return bulk_invalidate(client, keys + tag_keys)


def add_tag_to_key(client, key: str, tag: str, namespace: str = "default") -> bool:
    try:
        client.set(f"tag:{namespace}:{tag}:{key}", 1)
        return True
    except Exception as e:
        raise CacheInvalidationError(f"Error adding tag to key {key}: {e}")


def remove_tag_from_key(client, key: str, tag: str, namespace: str = "default") -> bool:
    try:
        client.delete(f"tag:{namespace}:{tag}:{key}")
        return True
    except Exception as e:
        raise CacheInvalidationError(f"Error removing tag from key {key}: {e}")


def list_keys_by_tag(client, tag: str, namespace: str = "default") -> List[str]:
    pattern = f"tag:{namespace}:{tag}:*"
    with _lock:
        return [_decode(k).split(":", 3)[-1] for k in client.keys(pattern)]


def list_tags_by_key(client, key: str, namespace: str = "default") -> List[str]:
    pattern = f"tag:{namespace}:*:{key}"
    with _lock:
        out = []
        for k in client.keys(pattern):
            parts = _decode(k).split(":", 3)
            if len(parts) == 4 and parts[3] == key:
                out.append(parts[2])
        return out


def set_key_info(client, key: str, metadata: Dict[str, Any],
                 namespace: str = "default") -> None:
    """Store JSON metadata for a key (paired with get_key_info)."""
    client.set(f"meta:{namespace}:{key}", json.dumps(metadata, sort_keys=True))


def get_key_info(client, key: str, namespace: str = "default") -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    meta_value = client.get(f"meta:{namespace}:{key}")
    if meta_value:
        try:
            info["metadata"] = json.loads(_decode(meta_value))
        except (TypeError, ValueError) as e:
            raise CacheInvalidationError(f"Corrupt metadata for {key}: {e}")
    return info


def subscribe_to_tag(client, tag: str, callback: Callable[[str], None],
                     namespace: str = "default") -> str:
    """Register an in-process callback fired when a key with this tag is invalidated.

    Uses a module-level registry (not redis pubsub) so it works with any
    redis-compatible client and offline.
    """
    subscription_id = f"sub:{namespace}:{tag}:{uuid.uuid4().hex[:8]}"
    with _lock:
        _subscriptions[subscription_id] = (namespace, tag, callback)
    return subscription_id


def unsubscribe_from_tag(client, subscription_id: str) -> bool:
    with _lock:
        return _subscriptions.pop(subscription_id, None) is not None


class _FakeRedis:
    """Minimal in-memory redis-compatible client for the offline selftest."""

    def __init__(self):
        self._d: Dict[str, Any] = {}

    def set(self, k, v):
        self._d[k] = v
        return True

    def get(self, k):
        return self._d.get(k)

    def delete(self, k):
        return 1 if self._d.pop(k, None) is not None else 0

    def keys(self, pattern="*"):
        import fnmatch
        return [k for k in list(self._d) if fnmatch.fnmatch(k, pattern)]


def _selftest() -> bool:
    c = _FakeRedis()
    c.set("user:1", "alice")
    c.set("user:2", "bob")
    c.set("page:home", "<html>")
    add_tag_to_key(c, "user:1", "users")
    add_tag_to_key(c, "user:2", "users")
    add_tag_to_key(c, "page:home", "pages")

    assert sorted(list_keys_by_tag(c, "users")) == ["user:1", "user:2"]
    assert list_tags_by_key(c, "user:1") == ["users"]

    fired: List[str] = []
    sid = subscribe_to_tag(c, "users", fired.append)

    assert invalidate_by_tag(c, "users") == 2
    assert c.get("user:1") is None and c.get("user:2") is None
    assert c.get("page:home") == "<html>"          # other tag untouched
    assert sorted(fired) == ["user:1", "user:2"]   # subscription fired
    assert unsubscribe_from_tag(c, sid)
    assert not unsubscribe_from_tag(c, sid)

    # prefix invalidation
    c.set("sess:a", 1)
    c.set("sess:b", 2)
    assert invalidate_prefix(c, "sess:") == 2

    # metadata: JSON only, never eval
    set_key_info(c, "page:home", {"ttl": 30, "owner": "web"})
    assert get_key_info(c, "page:home")["metadata"] == {"ttl": 30, "owner": "web"}
    c.set("meta:default:evil", "__import__('os').system('echo x')")
    try:
        get_key_info(c, "evil")
        raise AssertionError("non-JSON metadata accepted")
    except CacheInvalidationError:
        pass
    assert get_key_info(c, "no-meta") == {}

    # prefix+tag combined
    c.set("api:v1:x", 1)
    add_tag_to_key(c, "api:v1:x", "api")
    c.set("web:y", 1)
    add_tag_to_key(c, "web:y", "api")
    assert invalidate_by_prefix_and_tag(c, "api:", "api") == 1
    assert c.get("web:y") == 1

    # invalidate_all clears remaining tagged data + markers in namespace
    assert invalidate_all(c) >= 1
    assert not [k for k in c.keys("tag:default:*")]

    print("cache_invalidation selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
