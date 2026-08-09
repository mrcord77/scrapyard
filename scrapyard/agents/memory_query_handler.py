"""
memory_query_handler — Handles structured queries against a persistent agent memory store: parses key:value / AND / OR query strings into SQL over a configurable SQLite database and ranks the matches with real recall scoring from memory_recall_scoring.

### PART-META-JSON
{
  "name": "memory_query_handler",
  "layer": "agents",
  "purpose": "Query layer for agent memories: configure_db() opens (or creates) a SQLite memory store, add_memory() persists entries, parse_query() turns 'key:value', 'a AND b', 'a OR b' strings into structured conditions, and handle_query() runs them as parameterized SQL then ranks matches by semantic relevance using memory_recall_scoring embeddings.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "memory_recall_scoring"
  ],
  "inputs": "configure_db(path or ':memory:'); add_memory(content, metadata); handle_query('title:foo AND date:2023', context); process_request({'query': ..., 'context': {...}}).",
  "outputs": "List[MemoryEntry] (id, content, metadata, timestamp, score) ordered by descending relevance; process_request adds timing + request-id metadata.",
  "files_created": [
    "SQLite database at the path passed to configure_db()"
  ],
  "security_notes": "All metadata matching uses parameterized SQL (json_extract + ? placeholders) - query values are never interpolated into SQL strings, closing the injection hole the previous version had. Query strings are caller input: length is not capped here, so cap upstream if exposed to untrusted users. Scores come from local deterministic embeddings (no network).",
  "ai_usage": "configure_db(':memory:'); add_memory('note text', {'title': 'notes'}); entries = handle_query('title:notes', {}).",
  "example": "from scrapyard.agents.memory_query_handler import configure_db, add_memory, handle_query",
  "import_path": "scrapyard.agents.memory_query_handler"
}
### END-PART-META
"""
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import os, re, time, hashlib, logging, sqlite3, tempfile, json

from scrapyard.agents.memory_recall_scoring import (
    _generate_embedding, cosine_similarity,
)

logger = logging.getLogger(__name__)

_conn: Optional[sqlite3.Connection] = None

_KV = re.compile(r"(\w+):(\S.*)")


@dataclass
class MemoryEntry:
    id: int
    content: str
    metadata: Dict[str, Any]
    timestamp: datetime
    score: float = field(default=0.0)


def configure_db(path: str = ":memory:") -> None:
    """Open (or create) the memory store the handler queries."""
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = sqlite3.connect(path)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            timestamp TEXT NOT NULL
        )
    """)
    _conn.commit()


def close_db() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def _require_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Memory store not configured. Call configure_db() first.")
    return _conn


def add_memory(content: str, metadata: Optional[Dict[str, Any]] = None,
               timestamp: Optional[datetime] = None) -> int:
    """Persist a memory row and return its id."""
    conn = _require_conn()
    ts = (timestamp or datetime.now()).isoformat()
    cur = conn.execute(
        "INSERT INTO memories (content, metadata, timestamp) VALUES (?, ?, ?)",
        (content, json.dumps(metadata or {}), ts))
    conn.commit()
    return int(cur.lastrowid)


def parse_query(query: str) -> Dict[str, Any]:
    """Parse a structured query string into conditions.

    Supported forms:
      'key:value'                       -> {key: value}
      'key1:v1 AND key2:v2'             -> {'operator': 'and', 'conditions': [...]}
      'key1:v1 OR key2:v2'              -> {'operator': 'or', 'conditions': [...]}
      free text (no colon)              -> {'text': query}  (semantic-only)
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("Query must be a non-empty string")
    for op_word, op in ((" AND ", "and"), (" OR ", "or")):
        if op_word in query:
            parts = [p.strip() for p in query.split(op_word) if p.strip()]
            return {"operator": op, "conditions": [parse_query(p) for p in parts]}
    m = _KV.match(query)
    if m:
        return {m.group(1): m.group(2).strip()}
    return {"text": query}


def _conditions_to_sql(parsed: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """Build a parameterized WHERE clause from parsed conditions."""
    if "operator" in parsed:
        joiner = " AND " if parsed["operator"] == "and" else " OR "
        clauses, params = [], []
        for cond in parsed["conditions"]:
            sql, p = _conditions_to_sql(cond)
            if sql:
                clauses.append(f"({sql})")
                params.extend(p)
        return joiner.join(clauses), params
    if "text" in parsed:
        # free text: match content (semantic ranking happens afterwards)
        return "content LIKE ?", [f"%{parsed['text']}%"]
    clauses, params = [], []
    for key, value in parsed.items():
        # parameterized json_extract match; substring semantics like before
        clauses.append("COALESCE(json_extract(metadata, '$.' || ?), '') LIKE ?")
        params.extend([key, f"%{value}%"])
    return " AND ".join(clauses), params


def handle_query(query: str, context: dict) -> List[MemoryEntry]:
    """Run a structured query against the store and rank results by semantic
    relevance to the full query text (real recall scoring, not a constant)."""
    conn = _require_conn()
    parsed = parse_query(query)
    where, params = _conditions_to_sql(parsed)
    sql = "SELECT id, content, metadata, timestamp FROM memories"
    if where:
        sql += f" WHERE {where}"
    rows = conn.execute(sql, params).fetchall()

    query_vec = _generate_embedding(query, 64)
    scored: List[MemoryEntry] = []
    for entry_id, content, metadata, ts in rows:
        mem_vec = _generate_embedding(content, 64)
        score = max(0.0, cosine_similarity(query_vec, mem_vec))
        try:
            parsed_ts = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            parsed_ts = datetime.min
        scored.append(MemoryEntry(entry_id, content, json.loads(metadata),
                                  parsed_ts, score))
    scored.sort(key=lambda e: (-e.score, e.id))
    limit = context.get("limit") if isinstance(context, dict) else None
    return scored[:limit] if isinstance(limit, int) and limit > 0 else scored


def process_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """Processes a query request and returns a response."""
    start_time = time.time()
    result = handle_query(request["query"], request.get("context", {}))
    end_time = time.time()

    response = {
        "results": [entry.__dict__ for entry in result],
        "time_taken": end_time - start_time,
        "metadata": {"request_id": hashlib.md5(
            str(request).encode()).hexdigest()},
    }

    logger.info("Query processed: %s took %.2fs",
                response["metadata"]["request_id"], response["time_taken"])
    return response


def _selftest():
    """Self-test: real store, structured queries, real relevance ordering."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        configure_db(os.path.join(temp_dir, "memory.db"))
        try:
            add_memory("Introduction to scrapyard",
                       {"title": "scrapyard", "date": "2023-06-15"},
                       datetime(2023, 6, 15))
            add_memory("Advanced scrapyard techniques",
                       {"title": "scrapyard", "date": "2023-07-20"},
                       datetime(2023, 7, 20))
            add_memory("History of memory systems",
                       {"title": "history", "date": "2022-12-01"},
                       datetime(2022, 12, 1))

            # metadata AND query
            request = {"query": "title:scrapyard AND date:2023", "context": {}}
            response = process_request(request)
            assert len(response["results"]) == 2, response["results"]
            assert "time_taken" in response
            assert "metadata" in response

            # OR broadens the match set
            or_results = handle_query("title:scrapyard OR title:history", {})
            assert len(or_results) == 3

            # single key:value
            hist = handle_query("title:history", {})
            assert len(hist) == 1 and hist[0].metadata["title"] == "history"

            # free-text query ranks by real semantic relevance
            ranked = handle_query("scrapyard", {})
            assert len(ranked) == 2
            assert all("scrapyard" in e.content.lower() for e in ranked)
            assert ranked[0].score >= ranked[1].score > 0.0

            # scores differ across entries (not a constant)
            all_scores = {e.score for e in handle_query("title:scrapyard OR title:history", {})}
            assert len(all_scores) > 1, "scores must reflect relevance, not a constant"

            # injection attempt stays data, not SQL
            evil = handle_query("title:x' OR '1'='1", {})
            assert evil == []

            # limit honored via context
            limited = handle_query("title:scrapyard OR title:history", {"limit": 1})
            assert len(limited) == 1

            # unconfigured error path
            close_db()
            try:
                handle_query("title:x", {})
                raise AssertionError("expected RuntimeError when unconfigured")
            except RuntimeError:
                pass
        finally:
            close_db()

    print("Self-test passed successfully.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
