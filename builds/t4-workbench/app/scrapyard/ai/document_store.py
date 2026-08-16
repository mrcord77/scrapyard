"""
document_store — Durable RAG storage: documents, embedded chunks, retrieval logs.

Persists ingested documents and their embedded chunks so a corpus survives restarts
(unlike the in-memory vector store). Retrieval is cosine similarity over stored
chunk embeddings with optional metadata filtering, returning scored citations
(document + chunk + excerpt). Every retrieval is logged for cost/observability.

### PART-META-JSON
{
  "name": "document_store",
  "layer": "ai",
  "purpose": "Durable document/chunk storage with embedded-chunk retrieval (scored citations) and retrieval logging.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "DocumentStore(embedder): ingest(db, source_id, text, metadata, tenant_id); retrieve(db, query, k, filters, tenant_id); get/list/delete; log_retrieval.",
  "outputs": "Persisted AIDocument + AIChunk rows (with embeddings + content hash); retrieval returns scored citations; AIRetrievalLog records each query.",
  "files_created": [],
  "security_notes": "Ingestion is idempotent by content hash (re-ingesting identical text returns the existing document, no duplicate corpus). tenant_id scoping is enforced in retrieve/list/get so one tenant never sees another's chunks. Embeddings are stored as JSON vectors; the cosine scan is exact (correct, not ANN) — for large corpora use a pgvector/ANN backend (drop-in: keep this interface). Excerpts may contain source text; apply the same access controls you'd apply to the documents.",
  "ai_usage": "store = DocumentStore(embedder=provider.embed); store.ingest(db, 'doc1', text); hits = store.retrieve(db, 'question', k=4, filters={'lang':'en'}).",
  "example": "from scrapyard.ai.document_store import DocumentStore; s=DocumentStore(); s.ingest(db,'d1','text...'); s.retrieve(db,'q')",
  "import_path": "scrapyard.ai.document_store"
}
### END-PART-META
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime

STATUS = "core"

from sqlalchemy import String, Text, Integer, Float, DateTime, ForeignKey, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship
from scrapyard.database.base_model import IntPKModel


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


class AIDocument(IntPKModel):
    __tablename__ = "ai_documents"
    source_id: Mapped[str] = mapped_column(String(200), index=True)
    tenant_id: Mapped[str] = mapped_column(String(100), default="", index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    chunks: Mapped[list["AIChunk"]] = relationship(back_populates="document",
                                                   cascade="all, delete-orphan")


class AIChunk(IntPKModel):
    __tablename__ = "ai_chunks"
    document_id: Mapped[int] = mapped_column(ForeignKey("ai_documents.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(100), default="", index=True)
    idx: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    embedding_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    document: Mapped["AIDocument"] = relationship(back_populates="chunks")


class AIRetrievalLog(IntPKModel):
    __tablename__ = "ai_retrieval_logs"
    tenant_id: Mapped[str] = mapped_column(String(100), default="", index=True)
    query: Mapped[str] = mapped_column(Text, default="")
    chunk_ids: Mapped[str] = mapped_column(Text, default="[]")
    top_score: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    offline: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(x * x for x in b) ** 0.5 or 1.0
    return dot / (na * nb)


class DocumentStore:
    def __init__(self, embedder=None):
        if embedder is None:
            from scrapyard.ai.embeddings import embed
            embedder = embed
        self.embed = embedder
        self._audit_hooks = []
        self._tenant_config: dict[str, dict] = {}

    def register_audit_hook(self, hook) -> None:
        """Register hook(event: str, payload: dict) fired on ingest/retrieve/delete."""
        if not callable(hook):
            raise TypeError("hook must be callable")
        self._audit_hooks.append(hook)

    def _audit(self, event: str, payload: dict) -> None:
        for hook in self._audit_hooks:
            try:
                hook(event, payload)
            except Exception:
                pass  # observers never break the store

    def configure_for_tenant(self, tenant_id: str, config: dict) -> None:
        """Store per-tenant overrides (e.g. {'k': 8, 'max_chars': 800}) consulted
        by ingest/retrieve when no explicit value is passed."""
        if not isinstance(config, dict):
            raise ValueError("config must be a dict")
        self._tenant_config.setdefault(tenant_id, {}).update(config)

    def get_tenant_config(self, tenant_id: str) -> dict:
        return dict(self._tenant_config.get(tenant_id, {}))

    def ingest(self, db, source_id: str, text: str, *, metadata: dict | None = None,
               tenant_id: str = "", max_chars: int = 1200, overlap: int = 150) -> AIDocument:
        """Chunk -> embed -> persist. Idempotent by (tenant, content hash): identical
        text returns the existing document instead of duplicating the corpus."""
        from scrapyard.ai.chunking import chunk_text
        tcfg = self._tenant_config.get(tenant_id, {})
        max_chars = tcfg.get("max_chars", max_chars)
        overlap = tcfg.get("overlap", overlap)
        h = _hash(text)
        existing = db.scalars(select(AIDocument).where(
            AIDocument.tenant_id == tenant_id, AIDocument.content_hash == h).limit(1)).first()
        if existing:
            return existing
        doc = AIDocument(source_id=source_id, tenant_id=tenant_id, content_hash=h,
                         metadata_json=json.dumps(metadata or {}))
        db.add(doc); db.flush()
        for i, ch in enumerate(chunk_text(text, max_chars=max_chars, overlap=overlap)):
            db.add(AIChunk(document_id=doc.id, tenant_id=tenant_id, idx=i, text=ch,
                           embedding_json=json.dumps(self.embed(ch)),
                           metadata_json=json.dumps(metadata or {})))
        db.flush()
        self._audit("ingest", {"document_id": doc.id, "source_id": source_id,
                               "tenant_id": tenant_id})
        return doc

    def retrieve(self, db, query: str, *, k: int = 4, filters: dict | None = None,
                 tenant_id: str = "") -> list[dict]:
        """Cosine over stored chunk embeddings, optional metadata filter + tenant
        scope. Returns scored citations (highest first)."""
        qvec = self.embed(query)
        stmt = select(AIChunk).where(AIChunk.tenant_id == tenant_id)
        rows = list(db.scalars(stmt))
        scored = []
        for c in rows:
            meta = json.loads(c.metadata_json or "{}")
            if filters and any(meta.get(fk) != fv for fk, fv in filters.items()):
                continue
            score = _cosine(qvec, json.loads(c.embedding_json or "[]"))
            scored.append((score, c, meta))
        scored.sort(key=lambda t: t[0], reverse=True)
        out = []
        for score, c, meta in scored[:k]:
            out.append({"document_id": c.document_id, "chunk_id": c.id, "score": round(score, 4),
                        "excerpt": c.text[:300], "metadata": meta})
        self._audit("retrieve", {"query": query, "tenant_id": tenant_id,
                                 "hits": len(out)})
        return out

    def retrieve_paginated(self, db, query: str, *, page: int = 1, page_size: int = 20,
                           filters: dict | None = None, tenant_id: str = "") -> dict:
        """Cosine-ranked retrieval with page/page_size windows over the full
        ranked result set. Returns {'hits', 'total', 'page', 'page_size'}."""
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be >= 1")
        # rank everything, then window
        total_chunks = db.scalar(select(func.count()).select_from(AIChunk)
                                 .where(AIChunk.tenant_id == tenant_id)) or 0
        ranked = self.retrieve(db, query, k=max(total_chunks, 1),
                               filters=filters, tenant_id=tenant_id)
        start = (page - 1) * page_size
        return {"hits": ranked[start:start + page_size], "total": len(ranked),
                "page": page, "page_size": page_size}

    def get(self, db, document_id: int, *, tenant_id: str = "") -> AIDocument | None:
        doc = db.get(AIDocument, document_id)
        return doc if doc and doc.tenant_id == tenant_id else None

    def list(self, db, *, tenant_id: str = "", limit: int = 100) -> list[AIDocument]:
        return list(db.scalars(select(AIDocument).where(AIDocument.tenant_id == tenant_id)
                               .order_by(AIDocument.id.desc()).limit(limit)))

    def delete(self, db, document_id: int, *, tenant_id: str = "") -> bool:
        doc = self.get(db, document_id, tenant_id=tenant_id)
        if not doc:
            return False
        db.delete(doc); db.flush()   # chunks cascade
        return True

    def counts(self, db, *, tenant_id: str = "") -> dict:
        d = db.scalar(select(func.count()).select_from(AIDocument).where(AIDocument.tenant_id == tenant_id))
        c = db.scalar(select(func.count()).select_from(AIChunk).where(AIChunk.tenant_id == tenant_id))
        return {"documents": d or 0, "chunks": c or 0}

    def log_retrieval(self, db, query: str, hits: list[dict], usage: dict, offline: bool,
                      *, tenant_id: str = "") -> int:
        row = AIRetrievalLog(
            tenant_id=tenant_id, query=query[:2000],
            chunk_ids=json.dumps([h["chunk_id"] for h in hits]),
            top_score=(hits[0]["score"] if hits else 0.0),
            input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
            offline=1 if offline else 0)
        db.add(row); db.flush()
        return row.id


def _selftest():
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from scrapyard.database.base_model import IntPKModel

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'docs.db')}")
        IntPKModel.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            store = DocumentStore()
            events = []
            store.register_audit_hook(lambda ev, p: events.append(ev))

            d1 = store.ingest(db, "s1", "Python parts live in the scrapyard. "
                                        "Metadata describe each part.",
                              metadata={"lang": "en"})
            assert d1.id and len(d1.chunks) >= 1

            # idempotent by content hash
            d1b = store.ingest(db, "s1-again", "Python parts live in the scrapyard. "
                                               "Metadata describe each part.",
                               metadata={"lang": "en"})
            assert d1b.id == d1.id

            d2 = store.ingest(db, "s2", "Diesel engines need oil.",
                              metadata={"lang": "de"})
            db.commit()

            # retrieval is scored and ranked; filters and tenancy respected
            hits = store.retrieve(db, "python metadata", k=3)
            assert hits and hits[0]["document_id"] == d1.id
            assert hits[0]["score"] >= hits[-1]["score"]
            de_hits = store.retrieve(db, "anything", k=5, filters={"lang": "de"})
            assert all(h["document_id"] == d2.id for h in de_hits)
            assert store.retrieve(db, "python", k=3, tenant_id="other") == []

            # pagination
            pg = store.retrieve_paginated(db, "parts", page=1, page_size=1)
            assert len(pg["hits"]) == 1 and pg["total"] >= 2
            try:
                store.retrieve_paginated(db, "x", page=0)
                raise AssertionError("expected ValueError")
            except ValueError:
                pass

            # get/list/counts/delete
            assert store.get(db, d1.id).id == d1.id
            assert store.get(db, d1.id, tenant_id="other") is None
            assert len(store.list(db)) == 2
            c = store.counts(db)
            assert c["documents"] == 2 and c["chunks"] >= 2
            log_id = store.log_retrieval(db, "q", hits, {"input_tokens": 5}, True)
            assert log_id > 0
            assert store.delete(db, d2.id) is True
            db.commit()
            assert store.counts(db)["documents"] == 1

            # tenant config consulted at ingest
            store.configure_for_tenant("t1", {"max_chars": 30, "overlap": 5})
            d3 = store.ingest(db, "s3", "word " * 30, tenant_id="t1")
            assert len(d3.chunks) > 1, "tenant max_chars must drive chunking"

            # hooks observed real events
            assert "ingest" in events and "retrieve" in events
        finally:
            db.close()
            engine.dispose()

    print("document_store selftest passed")


if __name__ == "__main__":
    _selftest()
