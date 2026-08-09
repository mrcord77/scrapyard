"""
vector_store — Upsert/query vectors behind one interface.

### PART-META-JSON
{
  "name": "vector_store",
  "layer": "ai",
  "purpose": "In-memory vector store with cosine top-k search, metadata filtering, pagination, soft-delete archiving, bulk operations, serialization, and operation hooks - the same add/search/delete interface a pgvector or Pinecone adapter would expose, so callers can swap backends without code changes.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "embeddings"
  ],
  "inputs": "add(id, vector, metadata); search(query_vec, k); search_with_filters(...); get_by_id(id); archive(id); update(id, vector, metadata); delete/delete_many; serialize()/deserialize().",
  "outputs": "Scored hit dicts {id, score, metadata} ordered by cosine similarity; archived items keep their vectors but carry metadata['archived']=True and are excluded from search.",
  "files_created": [],
  "security_notes": "Purely in-process storage: nothing persists and nothing leaves the process, so treat it as a cache, not a system of record. deserialize() accepts caller-provided structures verbatim (no eval/exec, plain lists/dicts only) - validate provenance before loading serialized stores from disk or the network. Hooks run caller code on every operation; a raising hook is caught and logged, never allowed to corrupt the store.",
  "ai_usage": "store = VectorStore(); store.add('d1', embed(text), {'lang': 'en'}); hits = store.search(embed(query), k=5).",
  "example": "from scrapyard.ai.vector_store import VectorStore",
  "import_path": "scrapyard.ai.vector_store"
}
### END-PART-META
"""
from __future__ import annotations
import logging
from typing import List, Tuple, Dict, Any, Callable
from scrapyard.ai.embeddings import cosine

STATUS = "core"
logger = logging.getLogger(__name__)


class VectorStore:
    """In-memory vector store with cosine top-k search. Interface matches what a
    pgvector/Pinecone adapter would expose (add/search/delete)."""

    def __init__(self):
        self._items = []  # (id, vector, metadata)
        self._hooks: List[Callable[[str, Any], Any]] = []
        self._config: Dict[str, Any] = {}

    def add(self, id_: str, vector: List[float], metadata: Dict[str, Any] | None = None):
        self._items = [it for it in self._items if it[0] != id_]
        self._items.append((id_, vector, metadata or {}))
        self.apply_hooks("add", {"id": id_})

    def search(self, query_vec: List[float], k: int = 5) -> List[Dict[str, Any]]:
        scored = [{"id": i, "score": cosine(query_vec, v), "metadata": m}
                  for i, v, m in self._items if not m.get("archived")]
        self.apply_hooks("search", {"k": k, "candidates": len(scored)})
        return sorted(scored, key=lambda x: x["score"], reverse=True)[:k]

    def delete(self, id_: str) -> bool:
        n = len(self._items)
        self._items = [it for it in self._items if it[0] != id_]
        removed = len(self._items) < n
        if removed:
            self.apply_hooks("delete", {"id": id_})
        return removed

    def size(self) -> int:
        return len(self._items)

    def add_many(self, items: List[Tuple[str, List[float], Dict[str, Any] | None]]) -> None:
        """Bulk upsert vectors with metadata (same dedupe semantics as add)."""
        for id_, vector, metadata in items:
            if not isinstance(vector, list) or not all(isinstance(v, (int, float)) for v in vector):
                raise ValueError("Vector must be a list of numbers.")
            self.add(id_, vector, metadata)

    def search_with_filters(self, query_vec: List[float], k: int = 5,
                            filters: Dict[str, Any] | None = None,
                            page: int = 1, per_page: int = 20) -> List[Dict[str, Any]]:
        """Search vectors with metadata filters, then paginate the top-k hits."""
        if page < 1 or per_page < 1:
            raise ValueError("page and per_page must be >= 1")
        scored = [{"id": id_, "score": cosine(query_vec, vec), "metadata": meta}
                  for id_, vec, meta in self._items
                  if not meta.get("archived")
                  and (not filters or all(meta.get(fk) == fv for fk, fv in filters.items()))]
        topk = sorted(scored, key=lambda x: x["score"], reverse=True)[:k]
        start = (page - 1) * per_page
        return topk[start:start + per_page]

    def update(self, id_: str, vector: List[float] | None = None,
               metadata: Dict[str, Any] | None = None) -> bool:
        """Update vector and/or metadata for an existing ID."""
        for i, (item_id, vec, meta) in enumerate(self._items):
            if item_id == id_:
                new_vec = vector if vector is not None else vec
                new_meta = metadata if metadata is not None else meta
                self._items[i] = (id_, new_vec, new_meta)
                self.apply_hooks("update", {"id": id_})
                return True
        return False

    def delete_many(self, ids: List[str]) -> int:
        """Delete multiple entries by ID list."""
        n = len(self._items)
        self._items = [(id_, vec, meta) for (id_, vec, meta) in self._items if id_ not in ids]
        removed = n - len(self._items)
        if removed:
            self.apply_hooks("delete_many", {"ids": ids, "removed": removed})
        return removed

    def get_by_id(self, id_: str) -> Dict[str, Any] | None:
        """Retrieve vector and metadata by ID."""
        for item_id, vec, meta in self._items:
            if item_id == id_:
                return {"id": item_id, "vector": vec, **meta}
        return None

    def get_all(self, page: int = 1, per_page: int = 20) -> List[Dict[str, Any]]:
        """Get all vectors with metadata (paginated)."""
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        return [{"id": id_, "vector": vec, **meta}
                for id_, vec, meta in self._items][start_index:end_index]

    def archive(self, id_: str) -> bool:
        """Soft-delete a vector: keep the entry, mark metadata archived=True."""
        for i, (item_id, vec, meta) in enumerate(self._items):
            if item_id == id_:
                self._items[i] = (item_id, vec, {**meta, "archived": True})
                self.apply_hooks("archive", {"id": id_})
                return True
        return False

    def archive_many(self, ids: List[str]) -> int:
        """Soft-delete multiple vectors; returns how many were archived."""
        count = 0
        for i, (item_id, vec, meta) in enumerate(self._items):
            if item_id in ids and not meta.get("archived"):
                self._items[i] = (item_id, vec, {**meta, "archived": True})
                count += 1
        if count:
            self.apply_hooks("archive_many", {"ids": ids, "archived": count})
        return count

    def search_with_vector_and_filters(self, query_vec: List[float], k: int = 5,
                                       filters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        """Search with vector and metadata filters."""
        return self.search_with_filters(query_vec, k=k, filters=filters,
                                        page=1, per_page=k)

    def serialize(self) -> Dict[str, Any]:
        """Export data in a format suitable for backup or transfer."""
        return {"items": [list(it) for it in self._items], "config": dict(self._config)}

    def deserialize(self, data: Dict[str, Any]) -> None:
        """Import data from a serialized format."""
        items = data.get("items", [])
        restored = []
        for it in items:
            if not (isinstance(it, (list, tuple)) and len(it) == 3):
                raise ValueError("serialized item must be (id, vector, metadata)")
            id_, vec, meta = it
            restored.append((id_, list(vec), dict(meta or {})))
        self._items = restored
        self._config = dict(data.get("config", {}))

    def register_hook(self, hook: Callable[[str, Any], Any]) -> None:
        """Register an audit/metrics hook called as hook(operation, data)."""
        if not callable(hook):
            raise TypeError("hook must be callable")
        self._hooks.append(hook)

    def apply_hooks(self, operation: str, data: Any) -> None:
        """Invoke every registered hook; a raising hook is logged, not fatal."""
        for hook in self._hooks:
            try:
                hook(operation, data)
            except Exception as e:
                logger.warning("vector_store hook failed on %s: %s", operation, e)

    def configure(self, config: Dict[str, Any]) -> None:
        """Store runtime configuration values (merged)."""
        if not isinstance(config, dict):
            raise ValueError("config must be a dict")
        self._config.update(config)

    def get_config(self) -> Dict[str, Any]:
        """Access runtime configuration."""
        return {"status": STATUS, "dependencies": ["scrapyard.ai.embeddings"],
                **self._config}


def _selftest():
    from scrapyard.ai.embeddings import embed

    store = VectorStore()
    events = []
    store.register_hook(lambda op, data: events.append(op))

    va = embed("red apple fruit")
    vb = embed("green apple orchard")
    vc = embed("diesel engine parts")
    store.add("a", va, {"lang": "en", "topic": "fruit"})
    store.add("b", vb, {"lang": "en", "topic": "fruit"})
    store.add("c", vc, {"lang": "en", "topic": "machinery"})
    assert store.size() == 3

    # search ranks by real cosine similarity
    hits = store.search(embed("apple"), k=3)
    assert {h["id"] for h in hits[:2]} == {"a", "b"}
    assert hits[0]["score"] >= hits[1]["score"] >= hits[2]["score"]

    # get_by_id returns THE requested item (regression: parameter shadowing
    # used to return the first item for any id)
    got_c = store.get_by_id("c")
    assert got_c is not None and got_c["id"] == "c" and got_c["topic"] == "machinery"
    assert store.get_by_id("missing") is None

    # archive actually archives (regression: id_ != id_ archived nothing)
    assert store.archive("c") is True
    assert store.get_by_id("c")["archived"] is True
    assert store.size() == 3, "archive must not delete"
    assert all(h["id"] != "c" for h in store.search(embed("diesel engine"), k=3)), \
        "archived items must not surface in search"
    assert store.archive("missing") is False

    # archive_many keeps items and marks the right ones
    store.add("d", embed("spare bolts"), {})
    n = store.archive_many(["d", "nope"])
    assert n == 1 and store.get_by_id("d")["archived"] is True
    assert store.size() == 4

    # filters + pagination
    f_hits = store.search_with_filters(embed("apple"), k=2, filters={"topic": "fruit"})
    assert {h["id"] for h in f_hits} == {"a", "b"}
    page2 = store.search_with_filters(embed("apple"), k=2, filters={"topic": "fruit"},
                                      page=2, per_page=1)
    assert len(page2) == 1

    # update: both vector and metadata land (regression: stale-tuple overwrite)
    assert store.update("a", vector=vc, metadata={"topic": "changed"}) is True
    got_a = store.get_by_id("a")
    assert got_a["vector"] == vc and got_a["topic"] == "changed"
    assert store.update("missing") is False

    # delete / delete_many
    assert store.delete("a") is True and store.get_by_id("a") is None
    assert store.delete("a") is False
    assert store.delete_many(["b", "zzz"]) == 1

    # serialize round-trip
    blob = store.serialize()
    clone = VectorStore()
    clone.deserialize(blob)
    assert clone.size() == store.size()
    assert clone.get_by_id("c")["archived"] is True

    # config
    store.configure({"backend": "memory"})
    assert store.get_config()["backend"] == "memory"

    # hooks fired for real operations; a broken hook must not break the store
    assert "add" in events and "archive" in events and "delete" in events
    store.register_hook(lambda op, data: 1 / 0)
    store.add("e", embed("x"), {})  # must not raise

    # add_many validates vectors
    try:
        store.add_many([("bad", "not-a-vector", {})])
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    print("vector_store selftest passed")


if __name__ == "__main__":
    _selftest()
