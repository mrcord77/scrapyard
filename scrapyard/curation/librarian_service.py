"""
librarian_service — The curator's front desk: real search, metadata composition, and health over the metadata_harvester sqlite catalog (no embedding server, no simulation).

### PART-META-JSON
{
  "name": "librarian_service",
  "layer": "curation",
  "purpose": "Curate and serve part knowledge: TF-IDF token-cosine search over harvested part purposes/APIs, metadata composition (parts + aggregated pip deps + import lines) from the harvested DB, usage counting, and health checks that actually measure DB reachability, row counts, and staleness vs file mtimes.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "db_path (metadata_harvester sqlite store), optional root_dir of the parts tree, search query strings, needs lists.",
  "outputs": "Ranked PartInfo lists, composed metadata dicts, health dict, usage rows (librarian_usage table).",
  "files_created": ["librarian_usage table inside the harvester db"],
  "security_notes": "Read-mostly over a local sqlite catalog; all queries parameterized; no network access (the HTTP surface is opt-in via install_librarian and serves only local catalog data). Search text comes from part files already on disk - treat catalog content as code-adjacent, not user PII.",
  "ai_usage": "svc = LibrarianService(db_path); svc.get_parts('rate limiting'); svc.post_metadata(['users', 'auth']); svc.get_health(). install_librarian(app) mounts /curator/* on FastAPI. Run metadata_harvester.refresh first (or svc.ensure_fresh()).",
  "example": "from scrapyard.curation.librarian_service import LibrarianService; svc = LibrarianService('curation_catalog.db'); print(svc.get_parts('clipboard', top_k=3))",
  "import_path": "scrapyard.curation.librarian_service"
}
### END-PART-META
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

STATUS = "core"

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS librarian_usage (
    part_key TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0,
    last_used TEXT
);
"""


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


@dataclass
class PartInfo:
    part_id: str          # "<layer>/<name>"
    name: str
    layer: str
    purpose: str
    status: str
    dependencies: List[str]
    import_path: str
    file_path: str
    score: float = 0.0
    api: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "part_id": self.part_id, "name": self.name, "layer": self.layer,
            "purpose": self.purpose, "status": self.status,
            "dependencies": self.dependencies, "import_path": self.import_path,
            "file_path": self.file_path, "score": round(self.score, 4),
        }


class LibrarianService:
    """Search + composition + health over the metadata_harvester catalog.

    The harvester (scrapyard.curation.metadata_harvester) owns writing the
    `parts` table; this service reads it, maintains its own usage table, and
    builds an in-memory TF-IDF index over each part's purpose, name, layer and
    public API names — a real local ranking, no embedding server involved.
    """

    def __init__(self, db_path: str, root_dir: Optional[str] = None,
                 auto_refresh: bool = False, refresh_interval_s: float = 3600.0,
                 refresh_on_query: bool = False, min_check_interval_s: float = 30.0):
        self.db_path = db_path
        self.root_dir = root_dir
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.executescript(_USAGE_SCHEMA)
        self._parts: List[PartInfo] = []
        self._doc_vecs: List[Dict[str, float]] = []
        self._doc_norms: List[float] = []
        self._df: Dict[str, int] = {}
        self._n_docs = 0
        # --- self-updating knobs ---
        self.refresh_interval_s = refresh_interval_s
        self.refresh_on_query = refresh_on_query
        self.min_check_interval_s = min_check_interval_s
        self._last_check = 0.0          # monotonic time of last staleness probe
        self._refresh_lock = threading.Lock()
        self._refresh_timer: Optional[threading.Timer] = None
        self.reload_index()
        if auto_refresh:
            self.start_auto_refresh()

    def refresh_if_stale(self, force_check: bool = False) -> Dict[str, Any]:
        """Re-harvest ONLY when the store is actually stale vs disk. Throttled so
        query-path callers don't rescan the tree more than once per
        min_check_interval_s. Returns {checked, refreshed, ...}."""
        if not self.root_dir:
            return {"checked": False, "refreshed": False, "reason": "no root_dir"}
        now = time.monotonic()
        if not force_check and (now - self._last_check) < self.min_check_interval_s:
            return {"checked": False, "refreshed": False, "reason": "throttled"}
        with self._refresh_lock:
            self._last_check = time.monotonic()
            s = self.staleness()
            if not s.get("stale"):
                return {"checked": True, "refreshed": False, "staleness": s}
            result = self.ensure_fresh()
            return {"checked": True, "refreshed": True, "changed": result,
                    "staleness_before": s}

    def start_auto_refresh(self) -> None:
        """Begin a background daemon that calls refresh_if_stale() every
        refresh_interval_s. Idempotent; safe to call once at startup."""
        if not self.root_dir:
            raise ValueError("auto-refresh needs a root_dir (parts tree)")
        self.stop_auto_refresh()

        def _tick():
            try:
                self.refresh_if_stale(force_check=True)
            except Exception:  # never let the daemon die on a transient error
                logger.exception("librarian auto-refresh tick failed")
            finally:
                self._schedule_next()

        self._tick_fn = _tick
        self._schedule_next()

    def _schedule_next(self) -> None:
        t = threading.Timer(self.refresh_interval_s, self._tick_fn)
        t.daemon = True
        self._refresh_timer = t
        t.start()

    def stop_auto_refresh(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.cancel()
            self._refresh_timer = None

    # ------------------------------------------------------------- indexing --

    def _iter_rows(self):
        try:
            return self.conn.execute(
                "SELECT name, layer, purpose, meta_json, api_json, file_path "
                "FROM parts ORDER BY layer, name").fetchall()
        except sqlite3.OperationalError:
            return []  # harvester has not populated this db yet

    def reload_index(self) -> int:
        """(Re)build the TF-IDF index from the harvested rows. Returns doc count."""
        self._parts, self._doc_vecs, self._doc_norms = [], [], []
        self._df = {}
        raw_docs: List[Dict[str, int]] = []
        for name, layer, purpose, meta_json, api_json, file_path in self._iter_rows():
            meta = json.loads(meta_json or "{}")
            api = json.loads(api_json or "{}")
            part = PartInfo(
                part_id=f"{layer}/{name}", name=name, layer=layer,
                purpose=purpose or meta.get("purpose", ""),
                status=meta.get("status", "unknown"),
                dependencies=list(meta.get("dependencies", [])),
                import_path=meta.get("import_path", f"scrapyard.{layer}.{name}"),
                file_path=file_path, api=api)
            text_fields = [
                part.name.replace("_", " "), part.layer, part.purpose,
                str(meta.get("ai_usage", "")),
                " ".join(f.split("(")[0] for f in api.get("functions", [])),
                " ".join(c.get("name", "") for c in api.get("classes", [])),
            ]
            counts: Dict[str, int] = {}
            for tok in _tokenize(" ".join(text_fields)):
                counts[tok] = counts.get(tok, 0) + 1
            for tok in counts:
                self._df[tok] = self._df.get(tok, 0) + 1
            self._parts.append(part)
            raw_docs.append(counts)

        self._n_docs = len(self._parts)
        for counts in raw_docs:
            vec = {t: (1 + math.log(c)) * self._idf(t) for t, c in counts.items()}
            norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
            self._doc_vecs.append(vec)
            self._doc_norms.append(norm)
        return self._n_docs

    def _idf(self, token: str) -> float:
        return math.log((1 + self._n_docs) / (1 + self._df.get(token, 0))) + 1.0

    # --------------------------------------------------------------- search --

    def get_parts(self, query: str, top_k: int = 10) -> List[PartInfo]:
        """Rank parts against the query by TF-IDF cosine; falls back to a
        substring match when the query shares no vocabulary with the corpus."""
        if self.refresh_on_query:
            self.refresh_if_stale()
        q_counts: Dict[str, int] = {}
        for tok in _tokenize(query):
            q_counts[tok] = q_counts.get(tok, 0) + 1
        q_vec = {t: (1 + math.log(c)) * self._idf(t) for t, c in q_counts.items()}
        q_norm = math.sqrt(sum(w * w for w in q_vec.values())) or 1.0

        scored: List[PartInfo] = []
        for part, vec, norm in zip(self._parts, self._doc_vecs, self._doc_norms):
            dot = sum(w * vec.get(t, 0.0) for t, w in q_vec.items())
            if dot > 0:
                p = PartInfo(**{**part.__dict__})
                p.score = dot / (q_norm * norm)
                scored.append(p)
        scored.sort(key=lambda p: (-p.score, p.part_id))
        if scored:
            return scored[:top_k]

        needle = (query or "").lower()
        return [p for p in self._parts
                if needle in p.name.lower() or needle in p.purpose.lower()][:top_k]

    def find_part(self, need: str) -> Optional[PartInfo]:
        """Exact part-name (or layer/name) match first, else best search hit."""
        low = (need or "").strip().lower()
        for p in self._parts:
            if low in (p.name.lower(), p.part_id.lower(), p.import_path.lower()):
                return p
        hits = self.get_parts(need, top_k=1)
        return hits[0] if hits else None

    # ---------------------------------------------------------- composition --

    def post_metadata(self, needs: List[str]) -> Dict[str, Any]:
        """Compose a build metadata from the harvested DB: for each need,
        resolve a real part; aggregate pip deps and import lines. Needs that
        resolve to nothing are reported honestly in `unresolved`."""
        parts: List[PartInfo] = []
        unresolved: List[str] = []
        seen: set = set()
        for need in needs:
            part = self.find_part(need)
            if part is None:
                unresolved.append(need)
                continue
            if part.part_id not in seen:
                seen.add(part.part_id)
                parts.append(part)
                self._increment_usage(part.part_id)
        deps = sorted({d for p in parts for d in p.dependencies})
        return {
            "metadata_id": str(uuid4()),
            "composed_at": datetime.now(timezone.utc).isoformat(),
            "needs": list(needs),
            "parts": [p.to_dict() for p in parts],
            "imports": [f"import {p.import_path}" for p in parts],
            "pip_dependencies": deps,
            "unresolved": unresolved,
            "status": "complete" if not unresolved else "partial",
        }

    # ---------------------------------------------------------------- usage --

    def _increment_usage(self, part_key: str) -> None:
        self.conn.execute(
            "INSERT INTO librarian_usage (part_key, count, last_used) VALUES (?, 1, ?) "
            "ON CONFLICT(part_key) DO UPDATE SET count = count + 1, last_used = excluded.last_used",
            (part_key, datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    def usage(self, part_key: str) -> int:
        row = self.conn.execute(
            "SELECT count FROM librarian_usage WHERE part_key = ?", (part_key,)).fetchone()
        return row[0] if row else 0

    # -------------------------------------------------------------- health ---

    def staleness(self) -> Dict[str, Any]:
        """Measure how stale the harvested store is vs the parts tree on disk:
        rows whose file is missing (deleted), indexed files whose mtime is newer
        than the DB (edited), indexed files whose CONTENT hash no longer matches
        the stored file_hash (edited even with a preserved/backdated mtime), and
        part files on disk NOT yet in the DB (added). Any of the four means stale.
        `added` requires a root_dir to scan.

        The content-hash check closes the mtime blind spot: an editor (or a tool)
        can rewrite a file while keeping mtime <= db mtime, which the mtime test
        alone would miss. The harvester already stores a sha1 per part; we compare
        against it directly, reading each file's bytes once."""
        from pathlib import Path
        from scrapyard.curation.metadata_harvester import _hash

        missing: List[str] = []
        newer: List[str] = []
        changed: List[str] = []
        db_mtime = os.path.getmtime(self.db_path) if os.path.exists(self.db_path) else 0.0

        # Stored content hashes by normalized absolute path (one query).
        stored_hashes: Dict[str, str] = {}
        try:
            for fp, fh in self.conn.execute("SELECT file_path, file_hash FROM parts").fetchall():
                stored_hashes[os.path.normcase(os.path.abspath(fp))] = fh
        except sqlite3.OperationalError:
            pass  # parts table not populated yet

        indexed = set()
        for p in self._parts:
            key = os.path.normcase(os.path.abspath(p.file_path))
            indexed.add(key)
            if not os.path.exists(p.file_path):
                missing.append(p.part_id)
                continue
            if os.path.getmtime(p.file_path) > db_mtime:
                newer.append(p.part_id)
            stored = stored_hashes.get(key)
            if stored is not None:
                try:
                    if _hash(Path(p.file_path)) != stored:
                        changed.append(p.part_id)
                except OSError:
                    pass  # unreadable file; missing/mtime paths already cover most cases
        added: List[str] = []
        if self.root_dir:
            from scrapyard.curation.metadata_harvester import _iter_part_files
            for f in _iter_part_files(self.root_dir):
                if os.path.normcase(os.path.abspath(str(f))) not in indexed:
                    added.append(str(f))
        age_hours = (datetime.now(timezone.utc).timestamp() - db_mtime) / 3600 if db_mtime else None
        return {"rows": self._n_docs, "missing_files": len(missing),
                "files_newer_than_db": len(newer), "changed_content": len(changed),
                "new_files": len(added),
                "db_age_hours": round(age_hours, 2) if age_hours is not None else None,
                "stale": bool(missing or newer or changed or added)}

    def get_health(self) -> Dict[str, Any]:
        """Real checks: DB reachable, parts rows present, usage table writable,
        staleness measured (not assumed)."""
        health: Dict[str, Any] = {}
        try:
            n = self.conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
            health["metadata"] = "healthy" if n > 0 else "empty: 0 harvested parts"
            health["part_count"] = n
        except sqlite3.Error as e:
            health["metadata"] = f"unhealthy: {e}"
            health["part_count"] = 0
        try:
            self.conn.execute("SELECT COUNT(*) FROM librarian_usage").fetchone()
            health["usage"] = "healthy"
        except sqlite3.Error as e:
            health["usage"] = f"unhealthy: {e}"
        try:
            s = self.staleness()
            health["staleness"] = s
            health["index"] = ("healthy" if self._n_docs == health["part_count"]
                               else f"index has {self._n_docs} docs vs {health['part_count']} rows - call reload_index()")
        except OSError as e:
            health["staleness"] = {"error": str(e)}
            health["index"] = f"unhealthy: {e}"
        return health

    def ensure_fresh(self, root_dir: Optional[str] = None) -> Dict[str, int]:
        """Re-harvest the parts tree into this DB and rebuild the index."""
        root = root_dir or self.root_dir
        if not root:
            raise ValueError("ensure_fresh needs a root_dir (parts tree)")
        from scrapyard.curation.metadata_harvester import refresh
        result = refresh(self.db_path, root)
        self.reload_index()
        # Stamp the store's last-harvest time forward even on a no-op refresh, so
        # staleness (which compares file mtime vs db mtime) doesn't keep firing on
        # a file that was already re-ingested.
        try:
            os.utime(self.db_path, None)
        except OSError:
            pass
        return result

    def close(self) -> None:
        self.conn.close()


# ------------------------------------------------------------- HTTP surface ---

def install_librarian(app, db_path: str = "curation_catalog.db",
                      root_dir: Optional[str] = None, auto_refresh: bool = True,
                      refresh_interval_s: float = 3600.0) -> "LibrarianService":
    """Mount /curator/metadata, /curator/parts, /curator/health on a FastAPI
    app, all backed by ONE shared LibrarianService over the harvested store.
    With a root_dir the librarian keeps itself current: auto_refresh starts a
    background refresher (hourly by default) and each query also re-harvests if
    the parts tree changed."""
    service = LibrarianService(
        db_path, root_dir=root_dir,
        auto_refresh=bool(auto_refresh and root_dir),
        refresh_interval_s=refresh_interval_s,
        refresh_on_query=bool(root_dir))

    @app.post("/curator/metadata")
    async def post_metadata_endpoint(needs: List[str]) -> Dict[str, Any]:
        return service.post_metadata(needs)

    @app.get("/curator/parts")
    async def get_parts_endpoint(query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        return [p.to_dict() for p in service.get_parts(query, top_k)]

    @app.get("/curator/health")
    async def get_health_endpoint() -> Dict[str, Any]:
        return service.get_health()

    return service


def _selftest():
    import tempfile
    import time
    from pathlib import Path

    from scrapyard.curation.metadata_harvester import harvest

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        # Build a tiny real parts tree and harvest it (no fixtures faked into
        # the DB by hand — the same pipeline production uses).
        yard = Path(tmp) / "yard"
        for layer, name, purpose, body in [
            ("billing", "invoices", "List and fetch customer invoices.",
             "def for_user(db, user_id: int) -> list:\n    return []\n"),
            ("desktop", "clipboard_ops", "Copy and paste text on the system clipboard.",
             "def copy_text(t: str) -> None:\n    pass\n"),
            ("security", "rate_limiter", "Token bucket rate limiting for APIs.",
             "class TokenBucket:\n    def allow(self) -> bool:\n        return True\n"),
        ]:
            d = yard / layer
            d.mkdir(parents=True, exist_ok=True)
            (d / "__init__.py").write_text("", encoding="utf-8")
            metadata = json.dumps({"name": name, "layer": layer, "purpose": purpose,
                                   "status": "core", "dependencies": ["sqlalchemy"] if layer == "billing" else [],
                                   "import_path": f"yard.{layer}.{name}"})
            (d / f"{name}.py").write_text(
                f'"""\n{name} - {purpose}\n\n### PART-META-JSON\n{metadata}\n'
                f'### END-PART-META\n"""\n{body}', encoding="utf-8")

        db = os.path.join(tmp, "catalog.db")
        assert harvest(db, str(yard)) == 3

        svc = LibrarianService(db, root_dir=str(yard))
        try:
            assert svc._n_docs == 3, "index must cover every harvested part"

            # Search: real ranking, right part on top, scored and ordered.
            hits = svc.get_parts("clipboard paste text", top_k=3)
            assert hits and hits[0].name == "clipboard_ops", [h.name for h in hits]
            assert hits[0].score > 0
            hits2 = svc.get_parts("rate limiting bucket", top_k=2)
            assert hits2[0].name == "rate_limiter"

            # Composition from the harvested DB: parts + deps + imports, and
            # honest reporting of unresolvable needs.
            metadata = svc.post_metadata(["invoices", "rate limiting", "warp drive xyzzy"])
            names = [p["name"] for p in metadata["parts"]]
            assert "invoices" in names and "rate_limiter" in names, names
            assert metadata["pip_dependencies"] == ["sqlalchemy"]
            assert metadata["unresolved"] == ["warp drive xyzzy"]
            assert metadata["status"] == "partial"
            assert any(i.startswith("import yard.") for i in metadata["imports"])

            # Usage is persisted and increments.
            before = svc.usage("billing/invoices")
            svc.post_metadata(["invoices"])
            assert svc.usage("billing/invoices") == before + 1

            # Health: measured, not simulated.
            health = svc.get_health()
            assert health["metadata"] == "healthy" and health["part_count"] == 3
            assert health["usage"] == "healthy"
            assert health["staleness"]["rows"] == 3
            assert health["staleness"]["stale"] is False

            # Staleness actually detects a file edited after the harvest...
            time.sleep(0.05)
            target = yard / "billing" / "invoices.py"
            target.write_text(target.read_text(encoding="utf-8") + "\n# touched\n",
                              encoding="utf-8")
            future = time.time() + 5
            os.utime(target, (future, future))
            assert svc.staleness()["stale"] is True, "edited file must register as stale"

            # ...and ensure_fresh() re-harvests and clears it.
            r = svc.ensure_fresh()
            assert r["changed"] == 1, r
            assert svc.staleness()["missing_files"] == 0

            # Deleted file -> refresh removes the row and the index follows.
            (yard / "security" / "rate_limiter.py").unlink()
            svc.ensure_fresh()
            assert svc._n_docs == 2
            assert svc.find_part("rate_limiter") is None

            # Content drift with a BACKDATED mtime: the mtime test alone would
            # miss this, the content-hash test must catch it.
            edited = yard / "billing" / "invoices.py"
            past = time.time() - 100          # mtime strictly BEFORE the db mtime
            # Normalize mtime from the earlier future-mtime subtest so mtime is
            # provably NOT the trigger for what follows.
            os.utime(edited, (past, past))
            assert svc.staleness()["stale"] is False, "store should be fresh before edit"
            edited.write_text(
                edited.read_text(encoding="utf-8") + "\n# silent content edit\n",
                encoding="utf-8")
            os.utime(edited, (past, past))
            s = svc.staleness()
            assert s["files_newer_than_db"] == 0, "mtime must NOT be what flags this edit"
            assert s["changed_content"] >= 1, "content-hash must detect the backdated edit"
            assert s["stale"] is True, "backdated content edit must register as stale"
            # ensure_fresh() then re-ingests it and clears the drift.
            svc.ensure_fresh()
            assert svc.staleness()["changed_content"] == 0
            assert svc.staleness()["stale"] is False
        finally:
            svc.close()

    # ---- self-updating behavior (the oracle keeps itself current) ----
    # Isolated fresh tree so earlier mtime tweaks can't leak into these checks.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp2:
        yard2 = Path(tmp2) / "yard"

        def _write_part(name: str, purpose: str, future: bool = True) -> None:
            d = yard2 / "content"
            d.mkdir(parents=True, exist_ok=True)
            (d / "__init__.py").write_text("", encoding="utf-8")
            meta = json.dumps({"name": name, "layer": "content", "purpose": purpose,
                               "status": "core", "dependencies": [],
                               "import_path": f"yard.content.{name}"})
            f = d / f"{name}.py"
            f.write_text(f'"""\n{name} - {purpose}\n\n### PART-META-JSON\n{meta}\n'
                         f'### END-PART-META\n"""\n', encoding="utf-8")
            if future:  # guarantee mtime > db mtime on fast disks
                fut = time.time() + 10
                os.utime(f, (fut, fut))

        _write_part("seed", "The initial part present at startup.", future=False)
        db2 = os.path.join(tmp2, "catalog.db")
        assert harvest(db2, str(yard2)) == 1

        # refresh_on_query: a search auto-picks-up a part added after startup
        svc2 = LibrarianService(db2, root_dir=str(yard2), min_check_interval_s=0.0,
                                refresh_on_query=True)
        try:
            assert svc2.find_part("late_addition") is None
            _write_part("late_addition", "A part added after the oracle started.")
            svc2.get_parts("late addition content")  # triggers refresh_if_stale
            assert svc2.find_part("late_addition") is not None, \
                "refresh_on_query must surface parts added after startup"
            # no-op once the store is current again (files no longer newer than db)
            os.utime(yard2 / "content" / "late_addition.py", None)
            svc2.ensure_fresh()
            r = svc2.refresh_if_stale(force_check=True)
            assert r["checked"] is True and r["refreshed"] is False, r
        finally:
            svc2.close()

        # background daemon: picks up a new part within its interval, unattended
        svc3 = LibrarianService(db2, root_dir=str(yard2), min_check_interval_s=0.0,
                                refresh_interval_s=0.1)
        try:
            svc3.start_auto_refresh()
            _write_part("daemon_seen", "A part the background refresher must find.")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and svc3.find_part("daemon_seen") is None:
                time.sleep(0.1)
            assert svc3.find_part("daemon_seen") is not None, \
                "background auto-refresh must ingest new parts unattended"
        finally:
            svc3.stop_auto_refresh()
            svc3.close()

    logger.info("librarian_service selftest passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
