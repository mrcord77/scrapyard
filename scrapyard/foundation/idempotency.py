"""
idempotency — Idempotency-key store to dedupe unsafe retried requests.

### PART-META-JSON
{
  "name": "idempotency",
  "layer": "foundation",
  "purpose": "Idempotency-key store to dedupe unsafe retried requests: thread-safe in-memory TTL cache remembering each key's original result, plus run_once(key, fn) which executes fn at most once per key within the TTL and replays the stored result on retries.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Client-supplied idempotency keys and the callable guarding the unsafe operation.",
  "outputs": "The original operation result, replayed for duplicate keys until TTL expiry.",
  "files_created": [],
  "security_notes": "Scope keys per principal (e.g. hash(user_id + client key)) — raw client-chosen keys shared across users would let one caller replay another's stored response. The store is per-process; behind multiple workers use a shared backend or retries landing on another worker will re-execute. Stored results live in memory for the TTL, so avoid remembering large or sensitive payloads verbatim. Note run_once treats a stored None result as absent and will re-execute — return a sentinel, not None.",
  "ai_usage": "result = run_once(f'{user_id}:{idem_key}', lambda: charge_card(...)) inside POST handlers.",
  "example": "run_once('user1:abc123', lambda: create_order(payload))",
  "import_path": "scrapyard.foundation.idempotency"
}
### END-PART-META
"""
from __future__ import annotations
import threading, time
STATUS = "core"
class IdempotencyStore:
    """Remember idempotency keys + their stored response so retried requests return
    the original result instead of re-executing. In-memory; back with Redis in prod."""
    def __init__(self, ttl=86400): self._d={}; self._ttl=ttl; self._lock=threading.Lock()
    def seen(self, key):
        with self._lock:
            v=self._d.get(key)
            if v and v[1]>time.time(): return v[0]
            self._d.pop(key,None); return None
    def remember(self, key, result):
        with self._lock: self._d[key]=(result, time.time()+self._ttl)
store=IdempotencyStore()
def run_once(key, fn):
    prior=store.seen(key)
    if prior is not None: return prior
    r=fn(); store.remember(key, r); return r


def _selftest() -> None:
    calls = []
    s = IdempotencyStore(ttl=60)

    # remember/seen round trip
    assert s.seen("k1") is None
    s.remember("k1", {"order": 1})
    assert s.seen("k1") == {"order": 1}

    # TTL expiry evicts
    fast = IdempotencyStore(ttl=-1)
    fast.remember("gone", "x")
    assert fast.seen("gone") is None and "gone" not in fast._d

    # run_once executes once, replays after
    def op():
        calls.append(1)
        return {"result": len(calls)}
    global store
    saved = store
    try:
        store = IdempotencyStore(ttl=60)
        r1 = run_once("op-key", op)
        r2 = run_once("op-key", op)
        assert r1 == r2 == {"result": 1} and len(calls) == 1
        # distinct keys execute independently
        r3 = run_once("other-key", op)
        assert r3 == {"result": 2} and len(calls) == 2
    finally:
        store = saved

    # thread safety: concurrent remembers don't corrupt the dict
    import threading
    s2 = IdempotencyStore(ttl=60)
    def hammer(i):
        for j in range(200):
            s2.remember(f"k{i}-{j}", j)
            s2.seen(f"k{i}-{j}")
    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert s2.seen("k0-199") == 199

    print("idempotency selftest: PASS")


if __name__ == "__main__":
    _selftest()
