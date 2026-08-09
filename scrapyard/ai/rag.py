"""
rag — Retrieval-augmented generation orchestration.

### PART-META-JSON
{
  "name": "rag",
  "layer": "ai",
  "purpose": "Retrieval-augmented generation over the in-memory vector store: index/index_batch documents, retrieve (optionally with metadata filters and pagination), answer with grounded prompts and cited sources via the LLM client, plus store/llm configuration, hooks, bulk delete, and result serialization.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "llm_client",
    "vector_store",
    "embeddings",
    "jinja2"
  ],
  "inputs": "RAG(llm, store); index(doc_id, text, metadata); index_batch([{id, text, metadata}]); retrieve(question, k); retrieve_with_filters(question, filters); answer(question, k); answer_with_sources(question, summarize=).",
  "outputs": "answer -> {answer, sources, usage}; retrieve -> scored hits; index_batch validates document shape and raises DocumentFormatError.",
  "files_created": [],
  "security_notes": "Retrieved document text is interpolated verbatim into the LLM prompt - a poisoned document can steer the answer (classic indirect prompt injection), so gate ingestion (e.g. guardrails.enforce_input) when documents come from untrusted sources. Offline LLM answers are tagged '[offline:...]'. bulk_delete with filters iterates the store directly (no similarity query), so it deletes exactly the metadata matches.",
  "ai_usage": "rag = RAG(); rag.index('d1', text); print(rag.answer('question')['answer']).",
  "example": "from scrapyard.ai.rag import RAG",
  "import_path": "scrapyard.ai.rag"
}
### END-PART-META
"""
from __future__ import annotations
from typing import List, Dict, Any, Callable
from jinja2 import Template

STATUS = "core"


class NoResultsError(Exception):
    """Raised when no relevant documents are found."""
    pass


class LLMError(Exception):
    """Raised when the LLM client fails to generate an answer."""
    pass


class DocumentFormatError(Exception):
    """Raised when a document has invalid format."""
    pass


class FilterValidationError(Exception):
    """Raised when filter parameters are invalid."""
    pass


class RAG:
    """Retrieval-augmented generation: index documents, retrieve the most relevant
    by embedding similarity, build a grounded prompt, and answer via the LLM client."""

    def __init__(self, llm=None, store=None):
        from scrapyard.ai.llm_client import LLMClient
        from scrapyard.ai.vector_store import VectorStore
        self.llm = llm or LLMClient()
        self.store = store or VectorStore()
        self._hooks: Dict[str, List[Callable]] = {}
        self.metrics: List[Dict[str, Any]] = []

    # -- indexing -----------------------------------------------------------
    def index(self, doc_id: str, text: str, metadata: dict | None = None):
        from scrapyard.ai.embeddings import embed
        self.store.add(doc_id, embed(text), {**(metadata or {}), "text": text})
        self._fire("index", {"id": doc_id})

    def index_batch(self, docs: List[Dict[str, Any]]) -> None:
        """Index a list of {'id', 'text', 'metadata'?} documents. The whole batch
        is validated before any write so a malformed doc doesn't half-apply."""
        for doc in docs:
            if not isinstance(doc, dict) or not isinstance(doc.get("id"), str) \
                    or not isinstance(doc.get("text"), str):
                raise DocumentFormatError("Invalid document structure")
        for doc in docs:
            self.index(doc["id"], doc["text"], doc.get("metadata"))

    # -- retrieval ----------------------------------------------------------
    def retrieve(self, question: str, k: int = 3) -> list[dict]:
        from scrapyard.ai.embeddings import embed
        hits = self.store.search(embed(question), k=k)
        self._fire("retrieve", {"question": question, "hits": len(hits)})
        return hits

    def retrieve_with_filters(self, question: str, filters: Dict[str, Any],
                              sort: str = "similarity", k: int = 10) -> List[Dict[str, Any]]:
        """Retrieve, keep only hits whose metadata matches every filter, and sort
        (similarity: best first; anything else: ascending score)."""
        if not isinstance(filters, dict):
            raise FilterValidationError("Invalid filter parameters")
        # over-fetch so filtering doesn't starve the result set
        results = self.retrieve(question, k=max(k, self.store.size()))
        filtered = [hit for hit in results
                    if all(hit["metadata"].get(fk) == fv for fk, fv in filters.items())]
        filtered.sort(key=lambda x: x["score"], reverse=(sort == "similarity"))
        return filtered[:k]

    def paginate_retrieval(self, question: str, k: int = 10, page: int = 1,
                           page_size: int = 20) -> Dict[str, Any]:
        if page < 1 or page_size < 1:
            raise FilterValidationError("page and page_size must be >= 1")
        results = self.retrieve(question, k=k)
        start = (page - 1) * page_size
        return {"results": results[start:start + page_size], "total": len(results),
                "page": page, "page_size": page_size}

    # -- answering ----------------------------------------------------------
    def answer(self, question: str, k: int = 3) -> dict:
        hits = self.retrieve(question, k=k)
        context = "\n".join(h["metadata"].get("text", "") for h in hits)
        prompt = f"Use only this context to answer.\nContext:\n{context}\n\nQuestion: {question}"
        resp = self.llm.complete([{"role": "user", "content": prompt}])
        self.log_metrics({"op": "answer", "k": k, "usage": resp.get("usage", {})})
        return {"answer": resp["content"], "sources": [h["id"] for h in hits],
                "usage": resp.get("usage", {})}

    def answer_with_sources(self, question: str, k: int = 3,
                            summarize: bool = False) -> Dict[str, Any]:
        hits = self.retrieve(question, k=k)
        context = "\n".join(h["metadata"].get("text", "") for h in hits)
        prompt = f"Use only this context to answer.\nContext:\n{context}\n\nQuestion: {question}"
        try:
            resp = self.llm.complete([{"role": "user", "content": prompt}])
        except Exception as e:
            raise LLMError("Failed to generate answer") from e

        sources = [h["id"] for h in hits]
        if summarize:
            summary_template = Template(
                "Summarize the context and provide an answer: {{context}}\n\nQuestion: {{question}}")
            prompt_summary = summary_template.render(context=context, question=question)
            try:
                resp_summary = self.llm.complete([{"role": "user", "content": prompt_summary}])
            except Exception as e:
                raise LLMError("Failed to generate summary") from e
            return {"answer": resp["content"], "summary": resp_summary["content"],
                    "sources": sources, "usage": resp.get("usage", {})}
        return {"answer": resp["content"], "sources": sources,
                "usage": resp.get("usage", {})}

    # -- configuration / hooks / maintenance --------------------------------
    def configure_store(self, config: Dict[str, Any]) -> None:
        self.store.configure(config)

    def configure_llm(self, config: Dict[str, Any]) -> None:
        for key, value in (config or {}).items():
            if not hasattr(self.llm, key):
                raise ValueError(f"LLM client has no setting '{key}'")
            setattr(self.llm, key, value)

    def register_hook(self, hook_type: str, callback: Callable) -> None:
        """Register a callback fired on 'index' / 'retrieve' events."""
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._hooks.setdefault(hook_type, []).append(callback)

    def _fire(self, hook_type: str, payload: Dict[str, Any]) -> None:
        for cb in self._hooks.get(hook_type, []):
            try:
                cb(payload)
            except Exception:
                pass  # observer failures never break the pipeline

    def bulk_delete(self, ids: List[str] | None = None,
                    filters: Dict[str, Any] | None = None) -> int:
        """Delete by explicit ids OR by metadata filters (never both)."""
        if ids is not None and filters is not None:
            raise ValueError("Specify either 'ids' or 'filters', but not both")
        deleted = 0
        if ids is not None:
            for id_ in ids:
                if self.store.delete(id_):
                    deleted += 1
        elif filters is not None:
            # iterate the store directly - similarity search is wrong for deletes
            page = 1
            to_delete = []
            while True:
                batch = self.store.get_all(page=page, per_page=100)
                if not batch:
                    break
                for item in batch:
                    if all(item.get(fk) == fv for fk, fv in filters.items()):
                        to_delete.append(item["id"])
                page += 1
            for id_ in to_delete:
                if self.store.delete(id_):
                    deleted += 1
        return deleted

    def serialize_result(self, data: Dict[str, Any], format: str = "json") -> str:
        import json
        if format.lower() != "json":
            raise ValueError(f"Unsupported format: {format}")
        return json.dumps(data)

    def log_metrics(self, metrics: Dict[str, Any]) -> None:
        """Record a metrics event (kept in-memory; drain via .metrics)."""
        if not isinstance(metrics, dict):
            raise ValueError("metrics must be a dict")
        self.metrics.append(dict(metrics))


def _selftest():
    from scrapyard.ai.llm_client import LLMClient

    rag = RAG(llm=LLMClient(offline=True))
    events = []
    rag.register_hook("index", lambda p: events.append(("index", p["id"])))
    rag.register_hook("retrieve", lambda p: events.append(("retrieve", p["hits"])))

    # index_batch as a real method (regression: it was an orphaned module-level
    # function taking `self`)
    rag.index_batch([
        {"id": "d1", "text": "the scrapyard stores reusable python parts",
         "metadata": {"lang": "en", "topic": "library"}},
        {"id": "d2", "text": "diesel engines need regular oil changes",
         "metadata": {"lang": "en", "topic": "mechanics"}},
        {"id": "d3", "text": "python parts are catalogued with metadata",
         "metadata": {"lang": "en", "topic": "library"}},
    ])
    assert rag.store.size() == 3
    assert ("index", "d1") in events

    # bad batch rejected before any write
    try:
        rag.index_batch([{"id": 42, "text": "x"}])
        raise AssertionError("expected DocumentFormatError")
    except DocumentFormatError:
        pass
    assert rag.store.size() == 3

    # retrieval is similarity-ranked
    hits = rag.retrieve("python parts", k=2)
    assert {h["id"] for h in hits} <= {"d1", "d2", "d3"}
    assert hits[0]["id"] in ("d1", "d3")

    # retrieve_with_filters as a real method honoring metadata filters
    lib_hits = rag.retrieve_with_filters("python parts", {"topic": "library"}, k=5)
    assert {h["id"] for h in lib_hits} == {"d1", "d3"}
    try:
        rag.retrieve_with_filters("q", "not-a-dict")
        raise AssertionError("expected FilterValidationError")
    except FilterValidationError:
        pass

    # pagination
    page = rag.paginate_retrieval("python", k=3, page=1, page_size=2)
    assert page["total"] == 3 and len(page["results"]) == 2

    # grounded answer with sources (offline deterministic LLM)
    ans = rag.answer("what does the scrapyard store?", k=2)
    assert ans["answer"].startswith("[offline:") and len(ans["sources"]) == 2

    aws = rag.answer_with_sources("what does the scrapyard store?", k=1, summarize=True)
    assert "summary" in aws and aws["sources"]

    # config plumbing
    rag.configure_store({"backend": "memory"})
    assert rag.store.get_config()["backend"] == "memory"
    rag.configure_llm({"model": "claude-haiku-4"})
    assert rag.llm.model == "claude-haiku-4"
    try:
        rag.configure_llm({"no_such_setting": 1})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    # metrics recorded
    assert any(m["op"] == "answer" for m in rag.metrics)

    # serialization
    blob = rag.serialize_result({"a": 1})
    assert blob == '{"a": 1}'
    try:
        rag.serialize_result({}, format="xml")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    # bulk delete by filters hits exactly the metadata matches
    assert rag.bulk_delete(filters={"topic": "mechanics"}) == 1
    assert rag.store.get_by_id("d2") is None
    assert rag.bulk_delete(ids=["d1"]) == 1
    try:
        rag.bulk_delete(ids=["x"], filters={"a": 1})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    print("rag selftest passed")


if __name__ == "__main__":
    _selftest()
