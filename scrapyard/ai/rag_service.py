"""
rag_service — Grounded, cited answers over the durable document store.

Retrieves the most relevant stored chunks, builds a grounded prompt, calls the
configured provider, and returns the answer with full citations (document + chunk +
score + excerpt), token usage, an honest offline flag, and a retrieval-log id.

### PART-META-JSON
{
  "name": "rag_service",
  "layer": "ai",
  "purpose": "Retrieval-augmented answers with citations, usage accounting, and an honest offline flag.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "RagService(provider, store).answer(db, question, k, filters, tenant_id).",
  "outputs": "{answer, sources:[{document_id,chunk_id,score,excerpt}], model, usage, offline, retrieval_log_id, grounded}.",
  "files_created": [],
  "security_notes": "Answers are grounded only in retrieved tenant-scoped chunks; the prompt instructs the model to use the provided context and say so when it can't answer. `grounded` is false when nothing was retrieved (the caller should treat the answer as ungrounded). `offline` is true whenever the stub provider is used so a demo answer is never mistaken for real model output. Every call is logged (query, chunk ids, token usage) for cost control and audit.",
  "ai_usage": "svc = RagService(); svc.answer(db, 'question', k=4). Provider/embedder auto-resolve from env (offline by default).",
  "example": "from scrapyard.ai.rag_service import RagService; RagService().answer(db, 'What is X?')",
  "import_path": "scrapyard.ai.rag_service"
}
### END-PART-META
"""
from __future__ import annotations

STATUS = "core"

_PROMPT = (
    "You are a careful assistant. Answer the question using ONLY the context below. "
    "If the context does not contain the answer, say you don't have enough information.\n\n"
    "Context:\n{context}\n\nQuestion: {question}\nAnswer:"
)


class RagService:
    def __init__(self, provider=None, store=None):
        from scrapyard.ai.providers import get_provider
        self.provider = provider or get_provider()
        if store is None:
            from scrapyard.ai.document_store import DocumentStore
            store = DocumentStore(embedder=self.provider.embed)
        self.store = store
        self._prompt_template = _PROMPT
        self._usage_ledger: list = []

    def answer(self, db, question: str, *, k: int = 4, filters: dict | None = None,
               tenant_id: str = "") -> dict:
        if filters is None:
            filters = getattr(self, "_default_filters", None)
        hits = self.store.retrieve(db, question, k=k, filters=filters, tenant_id=tenant_id)
        context = "\n---\n".join(f"[chunk {h['chunk_id']}] {h['excerpt']}" for h in hits)
        prompt = self._prompt_template.format(
            context=context or "(no relevant context found)", question=question)
        resp = self.provider.complete([{"role": "user", "content": prompt}])
        offline = bool(getattr(self.provider, "offline", True))
        log_id = self.store.log_retrieval(db, question, hits, resp.get("usage", {}), offline,
                                          tenant_id=tenant_id)
        return {
            "answer": resp["content"],
            "sources": hits,
            "model": resp.get("model"),
            "usage": resp.get("usage", {}),
            "offline": offline,
            "grounded": bool(hits),
            "retrieval_log_id": log_id,
        }

    def set_prompt_template(self, template: str) -> None:
        """Replace the grounded-answer prompt. Must keep {context} and {question}
        placeholders so answers stay grounded in retrieved chunks."""
        if "{context}" not in template or "{question}" not in template:
            raise PromptTemplateError(
                "template must contain {context} and {question} placeholders")
        self._prompt_template = template

    def bulk_answer(self, db, questions, *, k: int = 4, filters: dict | None = None,
                    tenant_id: str = "") -> list:
        results = []
        for question in questions:
            result = self.answer(db, question, k=k, filters=filters, tenant_id=tenant_id)
            results.append(result)
        return results

    def add_filter_support(self, filters: dict) -> None:
        """Set default metadata filters applied when answer() is called without
        explicit filters."""
        if not isinstance(filters, dict):
            raise InvalidFilterError("Filters must be a dictionary")
        self._default_filters = filters

    def retrieve_paginated(self, db, question: str, page: int = 1, page_size: int = 20,
                           filters: dict | None = None, tenant_id: str = "") -> dict:
        if not isinstance(page, int) or not isinstance(page_size, int):
            raise InvalidFilterError("Page and page_size must be integers")
        hits = self.store.retrieve_paginated(db, question, page=page, page_size=page_size,
                                             filters=filters, tenant_id=tenant_id)
        context = "\n---\n".join(f"[chunk {h['chunk_id']}] {h['excerpt']}" for h in hits["hits"])
        prompt = self._prompt_template.format(context=context or "(no relevant context found)", question=question)
        resp = self.provider.complete([{"role": "user", "content": prompt}])
        offline = bool(getattr(self.provider, "offline", True))
        log_id = self.store.log_retrieval(db, question, hits["hits"], resp.get("usage", {}), offline,
                                          tenant_id=tenant_id)
        return {
            **hits,
            "answer": resp["content"],
            "sources": hits["hits"],
            "model": resp.get("model"),
            "usage": resp.get("usage", {}),
            "offline": offline,
            "grounded": bool(hits["hits"]),
            "retrieval_log_id": log_id,
        }

    def set_embedder(self, embedder) -> None:
        """Swap the embedding function used for retrieval (the store's .embed)."""
        if not callable(embedder):
            raise ValueError("embedder must be callable")
        self.store.embed = embedder

    def track_usage(self, usage: dict, tenant_id: str = "") -> None:
        """Record token usage. Delegates to the provider when it supports
        tracking; otherwise keeps a local per-service ledger."""
        if not isinstance(usage, dict):
            raise UsageTrackingError("usage must be a dict")
        if hasattr(self.provider, "track_usage"):
            try:
                self.provider.track_usage(usage, tenant_id=tenant_id)
                return
            except Exception as e:
                raise UsageTrackingError(f"Failed to track usage: {e}")
        self._usage_ledger.append({"tenant_id": tenant_id, **usage})

    def get_usage(self, tenant_id: str | None = None) -> list:
        if tenant_id is None:
            return list(self._usage_ledger)
        return [u for u in self._usage_ledger if u.get("tenant_id") == tenant_id]

    def register_audit_hook(self, hook) -> None:
        self.store.register_audit_hook(hook)

    def set_offline_mode(self, enabled: bool) -> None:
        if not hasattr(self.provider, "offline"):
            raise OfflineModeNotSupportedError("Provider does not support offline mode")
        self.provider.offline = enabled

    def validate_answer(self, answer: str, context: str) -> bool:
        """Weak grounding check: every alphanumeric token of the answer that is
        longer than 3 chars must appear in the context. Heuristic only."""
        import re as _re
        tokens = [t for t in _re.findall(r"[a-z0-9]+", (answer or "").lower())
                  if len(t) > 3]
        if not tokens:
            return False
        low_ctx = (context or "").lower()
        return all(t in low_ctx for t in tokens)

    def serialize_answer(self, answer: dict) -> str:
        """JSON-serialize an answer payload with HTML-escaped string values so
        it can be embedded in a page without script injection."""
        import html as _html
        import json as _json

        def _esc(v):
            if isinstance(v, str):
                return _html.escape(v)
            if isinstance(v, dict):
                return {k: _esc(x) for k, x in v.items()}
            if isinstance(v, list):
                return [_esc(x) for x in v]
            return v

        return _json.dumps(_esc(answer))

    def configure_for_tenant(self, tenant_id: str, config: dict) -> None:
        self.store.configure_for_tenant(tenant_id, config)


class NoRelevantChunksError(Exception):
    pass


class ProviderNotConfiguredError(Exception):
    pass


class InvalidFilterError(Exception):
    pass


class TenantNotFoundError(Exception):
    pass


class TenantUnauthorizedError(Exception):
    pass


class UsageTrackingError(Exception):
    pass


class PromptTemplateError(Exception):
    pass


class RateLimitExceededError(Exception):
    pass


class OfflineModeNotSupportedError(Exception):
    pass


def _selftest():
    import tempfile
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from scrapyard.database.base_model import IntPKModel
    from scrapyard.ai.document_store import DocumentStore
    from scrapyard.ai.providers import OfflineProvider

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'rag.db')}")
        IntPKModel.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            provider = OfflineProvider()
            store = DocumentStore(embedder=provider.embed)
            svc = RagService(provider=provider, store=store)

            audit = []
            svc.register_audit_hook(lambda ev, payload: audit.append(ev))

            store.ingest(db, "d1", "The scrapyard library stores reusable python parts. "
                                   "Each part carries metadata.",
                         metadata={"lang": "en"})
            store.ingest(db, "d2", "Diesel engines require oil changes every "
                                   "five thousand miles.", metadata={"lang": "en"})
            db.commit()

            # grounded cited answer
            res = svc.answer(db, "what does the scrapyard library store?", k=2)
            assert res["grounded"] is True and res["offline"] is True
            assert res["sources"] and res["retrieval_log_id"] > 0
            assert "ingest" in audit and "retrieve" in audit

            # bulk answers
            bulk = svc.bulk_answer(db, ["python parts?", "oil changes?"], k=1)
            assert len(bulk) == 2 and all(b["answer"] for b in bulk)

            # custom prompt template used for real
            svc.set_prompt_template("CTX {context} Q {question}")
            r2 = svc.answer(db, "python parts", k=1)
            assert r2["answer"].startswith("[offline")
            try:
                svc.set_prompt_template("no placeholders")
                raise AssertionError("expected PromptTemplateError")
            except PromptTemplateError:
                pass
            svc.set_prompt_template(_PROMPT)

            # paginated retrieval (regression: store method did not exist)
            pg = svc.retrieve_paginated(db, "parts", page=1, page_size=1)
            assert pg["page_size"] == 1 and len(pg["hits"]) == 1 and pg["total"] >= 1
            try:
                svc.retrieve_paginated(db, "x", page="one")
                raise AssertionError("expected InvalidFilterError")
            except InvalidFilterError:
                pass

            # default filters
            svc.add_filter_support({"lang": "en"})
            assert svc.answer(db, "python", k=1)["grounded"] is True
            try:
                svc.add_filter_support("nope")
                raise AssertionError("expected InvalidFilterError")
            except InvalidFilterError:
                pass

            # usage ledger (regression: delegated to a method providers lack)
            svc.track_usage({"input_tokens": 10, "output_tokens": 2}, tenant_id="t1")
            assert svc.get_usage("t1")[0]["input_tokens"] == 10

            # embedder swap actually changes the store's embedding fn
            svc.set_embedder(lambda text: [1.0, 0.0])
            assert store.embed("x") == [1.0, 0.0]
            svc.set_embedder(provider.embed)

            # answer validation heuristic
            assert svc.validate_answer("reusable python parts",
                                       "the scrapyard stores reusable python parts")
            assert not svc.validate_answer("quantum blockchain", "python parts")

            # serialization escapes HTML (regression: html.escape bogus kwargs)
            blob = svc.serialize_answer({"answer": "<script>x</script>", "n": 1})
            assert "<script>" not in blob and "&lt;script&gt;" in blob

            # tenant config + offline toggle
            svc.configure_for_tenant("t1", {"max_chars": 500})
            assert store.get_tenant_config("t1")["max_chars"] == 500
            svc.set_offline_mode(True)
            assert svc.provider.offline is True
        finally:
            db.close()
            engine.dispose()

    print("rag_service selftest passed")


if __name__ == "__main__":
    _selftest()
