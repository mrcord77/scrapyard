"""
embedding_index — embedding index

### PART-META-JSON
{
  "name": "embedding_index",
  "layer": "curation",
  "purpose": "embedding index",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: build_index(db_path, part_ids); search(db_path, query, top_k); refresh_index(db_path); get_part_metadata(db_path, part_id); EmbeddingIndex(...).",
  "outputs": "Returns: build_index -> None; search -> List[Dict[str, Any]]; refresh_index -> None; get_part_metadata -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import what you need from `scrapyard.curation.embedding_index`.",
  "example": "from scrapyard.curation.embedding_index import *",
  "import_path": "scrapyard.curation.embedding_index"
}
### END-PART-META
"""
from sqlalchemy import String, DateTime, JSON, select, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import List, Dict, Any
import os, hashlib, logging, tempfile

logger = logging.getLogger(__name__)

class EmbeddingIndex(IntPKModel):
    __tablename__ = "embedding_index"
    part_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    layer: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    embedding: Mapped[Dict[str, float]] = mapped_column(JSON, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("part_id", "layer", name="uq_part_id_layer"),
    )

def _embed(text: str) -> List[float]:
    """Deterministic 16-dim embedding of a token. Used for BOTH indexed parts and
    query strings so they share one vector space (a query equal to a part_id maps
    to that part's exact stored vector -> distance 0). Offline, dependency-free;
    swap in a real embedding model here without touching search()."""
    h = hashlib.md5((text or "").encode()).hexdigest()
    return [float(int(h[i:i + 2], 16)) for i in range(0, 32, 2)]


def _euclid_sq(a: List[float], b: List[float]) -> float:
    """Squared Euclidean distance; ranks identically to L2 but avoids the sqrt."""
    n = min(len(a), len(b))
    return sum((a[i] - b[i]) ** 2 for i in range(n)) + \
        sum(v * v for v in a[n:]) + sum(v * v for v in b[n:])


def build_index(db_path: str, part_ids: List[str]) -> None:
    from scrapyard.curation.metadata_harvester import get_part_info
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{db_path}")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    for part_id in part_ids:
        try:
            part_info = get_part_info(db_path, part_id)
            layer = part_info.get("layer")
            if not layer:
                logger.warning(f"Part {part_id} has no layer, skipping.")
                continue

            # Deterministic embedding (see _embed; shared with search()).
            embedding = {"vector": _embed(part_id)}

            # Check if record exists
            existing = session.execute(
                select(EmbeddingIndex).where(
                    EmbeddingIndex.part_id == part_id,
                    EmbeddingIndex.layer == layer
                )
            ).scalar_one_or_none()

            if existing:
                existing.embedding = embedding
                existing.last_updated = datetime.now(timezone.utc)
            else:
                session.add(EmbeddingIndex(
                    part_id=part_id,
                    layer=layer,
                    embedding=embedding,
                    last_updated=datetime.now(timezone.utc)
                ))
        except Exception as e:
            logger.error(f"Error building index for {part_id}: {e}")
            continue

    session.commit()
    session.close()

def search(db_path: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Nearest-neighbour search over the SAME persistent index build_index() wrote.

    Embeds ``query`` into the shared vector space, scores every stored part by
    squared Euclidean distance, and returns the ``top_k`` closest (nearest first,
    each with its ``distance``). Querying a part's own id returns that part first
    at distance 0.0.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    query_vector = _embed(query)

    engine = create_engine(f"sqlite:///{db_path}")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        rows = session.execute(select(EmbeddingIndex)).scalars().all()
        scored = []
        for r in rows:
            vec = (r.embedding or {}).get("vector", [])
            scored.append((_euclid_sq(query_vector, vec), r))
        # Nearest first; tie-break on part_id for a stable, deterministic order.
        scored.sort(key=lambda t: (t[0], t[1].part_id))
        return [
            {
                "part_id": r.part_id,
                "layer": r.layer,
                "distance": dist,
                "embedding": r.embedding,
                "last_updated": r.last_updated,
            }
            for dist, r in scored[:top_k]
        ]
    finally:
        session.close()
        engine.dispose()

def refresh_index(db_path: str) -> None:
    from scrapyard.curation.metadata_harvester import list_all_parts
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{db_path}")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Delete all existing records
    session.query(EmbeddingIndex).delete()
    session.commit()

    # Rebuild index with all parts
    part_ids = list_all_parts(db_path)
    build_index(db_path, part_ids)

    session.close()

def get_part_metadata(db_path: str, part_id: str) -> Dict[str, Any]:
    """Look up a harvested part's metadata by its ``layer/name`` part_id.

    Fix history: previously called ``get_part_info(part_id)`` but that function's
    signature is ``get_part_info(db_path, name, layer=None)`` — the single
    argument landed in ``db_path`` and the call always failed. Now splits the
    part_id and passes db_path + name + layer correctly.
    """
    from scrapyard.curation.metadata_harvester import get_part_info
    layer, _, name = part_id.partition("/")
    return get_part_info(db_path, name or part_id, layer or None)

def _selftest() -> None:
    """Offline self-test: build_index persists a deterministic embedding per part
    into a real SQLite table, keyed uniquely by (part_id, layer); a part with no
    layer is skipped; and search() runs a REAL nearest-neighbour query over that
    SAME persistent index (not a fresh empty in-memory DB, as the prior stub did).

    Falsifiable NN case: querying a part's own id returns that part first at
    distance 0.0; an unrelated query does NOT rank it first. On the old stub
    (which queried ``sqlite:///:memory:``) search() returned [] and these
    assertions fail.
    """
    from unittest.mock import patch
    from sqlalchemy import create_engine, select as _select
    from sqlalchemy.orm import Session as _Session

    def _expected_vec(pid: str):
        return _embed(pid)

    def _dist(a, b):
        return _euclid_sq(a, b)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "emb.db")
        engine = create_engine(f"sqlite:///{db_path}")
        EmbeddingIndex.metadata.create_all(engine)

        layers = {"alpha": "search", "beta": "agents", "gamma": "search", "orphan": None}

        def fake_get_part_info(_db_path, name, *a, **k):
            return {"name": name, "layer": layers.get(name)}

        with patch("scrapyard.curation.metadata_harvester.get_part_info",
                   side_effect=fake_get_part_info):
            build_index(db_path, ["alpha", "beta", "gamma", "orphan"])

        with _Session(engine) as s:
            rows = s.execute(_select(EmbeddingIndex)).scalars().all()
            by_id = {r.part_id: r for r in rows}

            # Parts with a layer are persisted...
            assert set(by_id) == {"alpha", "beta", "gamma"}, f"unexpected rows: {set(by_id)}"
            # ...and the layerless part is skipped (negative/adversarial case).
            assert "orphan" not in by_id, "part with no layer must be skipped, not indexed"

            # The stored embedding matches the deterministic generator exactly.
            assert by_id["alpha"].embedding["vector"] == _expected_vec("alpha")
            assert by_id["alpha"].layer == "search"

            # Nearest-neighbour sanity: alpha's own embedding is closest to alpha
            # (distance 0) and strictly closer than to any other part.
            va = by_id["alpha"].embedding["vector"]
            self_d = _dist(va, _expected_vec("alpha"))
            assert self_d == 0.0
            others = [_dist(va, by_id[p].embedding["vector"]) for p in ("beta", "gamma")]
            assert all(self_d < d for d in others), "a part must be its own nearest neighbour"

            # Re-running build_index updates in place (unique (part_id, layer)), no dupes.
            with patch("scrapyard.curation.metadata_harvester.get_part_info",
                       side_effect=fake_get_part_info):
                build_index(db_path, ["alpha"])
            again = s.execute(_select(EmbeddingIndex)).scalars().all()
            assert len([r for r in again if r.part_id == "alpha"]) == 1, "duplicate row on rebuild"

        engine.dispose()

        # --- REAL nearest-neighbour search over the persistent index -----------
        # Querying a part's own id returns THAT part first, at distance 0.
        hits = search(db_path, "alpha", top_k=3)
        assert hits, "search must return results from the persistent index (stub returned [])"
        assert hits[0]["part_id"] == "alpha", f"nearest to 'alpha' must be alpha: {hits}"
        assert hits[0]["distance"] == 0.0, f"a part is distance 0 from its own id: {hits[0]}"
        # Results are ordered nearest-first (non-decreasing distance).
        dists = [h["distance"] for h in hits]
        assert dists == sorted(dists), f"results must be nearest-first: {dists}"

        # Query 'beta' -> beta ranks first, and NOT alpha (falsifiable ordering).
        hb = search(db_path, "beta", top_k=3)
        assert hb[0]["part_id"] == "beta", f"nearest to 'beta' must be beta: {hb}"
        assert hb[0]["part_id"] != "alpha"

        # NEGATIVE: an unrelated query does not rank alpha first, and alpha's
        # distance is strictly positive (it is not a spurious 0-distance match).
        hu = search(db_path, "totally-unrelated-token-xyzzy", top_k=3)
        assert hu[0]["part_id"] != "alpha", f"unrelated query must not surface alpha first: {hu}"
        alpha_d = next(h["distance"] for h in hu if h["part_id"] == "alpha")
        assert alpha_d > 0.0, "unrelated query must be at positive distance from alpha"

        # top_k is honored (only 3 parts indexed, ask for 2).
        assert len(search(db_path, "alpha", top_k=2)) == 2

    print("embedding_index selftest: PASS (build + real persistent NN search, "
          "incl. unrelated-query negative)")


if __name__ == "__main__":
    _selftest()
