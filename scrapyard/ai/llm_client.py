"""
llm_client — Provider-agnostic chat/completions client.

### PART-META-JSON
{
  "name": "llm_client",
  "layer": "ai",
  "purpose": "Provider-agnostic chat client delegating to scrapyard.ai.providers (Anthropic, OpenAI, or the deterministic offline stub): complete()/bulk_complete() with per-call history recording, query_history() over in-memory records with optional SQLite persistence, and JSON-based serialize_call()/deserialize_call() round-tripping.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "providers",
    "httpx",
    "pydantic"
  ],
  "inputs": "LLMClient(model, offline=None, provider=None); complete(messages, max_tokens); bulk_complete([messages,...]); enable_history_db(path); query_history({'model':..., 'content_contains':...}, limit, offset); serialize_call/deserialize_call.",
  "outputs": "complete -> {content, model, usage}; query_history -> list of history records (model, messages, response, offline, ts); serialize_call -> JSON string.",
  "files_created": [
    "Optional SQLite history db at the path passed to enable_history_db()"
  ],
  "security_notes": "API keys come from env (ANTHROPIC_API_KEY / OPENAI_API_KEY via providers.py) and are sent only to the provider's official endpoint over HTTPS, never logged. History records store full prompts and responses - enable_history_db() persists them to disk, so point it at a protected location and scrub PII upstream if prompts may contain it. Offline mode is deterministic and clearly tagged '[offline:...]' so stub output can't pass as real model output. deserialize_call uses json.loads only (the old jinja2-render path executed template syntax embedded in serialized data and is gone).",
  "ai_usage": "c = LLMClient(); r = c.complete([{'role':'user','content':'hi'}]); c.query_history({'model': c.model}).",
  "example": "from scrapyard.ai.llm_client import LLMClient",
  "import_path": "scrapyard.ai.llm_client"
}
### END-PART-META
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
from typing import Optional, List, Dict, Any
from httpx import AsyncClient, HTTPError, RequestError
from pydantic import BaseModel

STATUS = "core"


class LLMProviderError(Exception):
    pass


class LLMOfflineError(LLMProviderError):
    pass


class LLMBulkError(LLMProviderError):
    pass


class ModelConfig(BaseModel):
    max_tokens: int = 1024
    temperature: float = 0.7
    presence_penalty: float = 0
    frequency_penalty: float = 0


class RetryConfig(BaseModel):
    attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 16.0
    backoff_factor: float = 2.0
    jitter: bool = True


class RateLimitConfig(BaseModel):
    limit: int = 500
    interval: float = 30.0


class LLMPolicy:
    def __init__(self, rate_limit: RateLimitConfig, model_config: ModelConfig):
        self.rate_limit = rate_limit
        self.model_config = model_config


class LLMClient:
    """Provider-agnostic chat client. Delegates real calls to
    scrapyard.ai.providers (Anthropic/OpenAI resolved from env); without a key it
    runs in deterministic offline mode (clearly tagged stub) so the whole AI
    stack is testable without network or spend."""

    def __init__(self, model: str = "claude-sonnet-4", *,
                 offline: bool | None = None, provider=None):
        self.model = model
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY")
                       or os.environ.get("OPENAI_API_KEY"))
        self.offline = (not has_key) if offline is None else offline
        self._provider = provider
        self.calls: List[List[Dict[str, Any]]] = []
        self.history: List[Dict[str, Any]] = []
        self._history_db: Optional[str] = None

    # -- provider resolution ------------------------------------------------
    def _resolve_provider(self):
        if self._provider is not None:
            return self._provider
        from scrapyard.ai.providers import (get_provider, OfflineProvider,
                                            AnthropicProvider)
        if self.offline:
            return OfflineProvider(model=f"offline-{self.model}")
        p = get_provider()
        if getattr(p, "offline", False):
            # env had no key after all: stay honest about being offline
            self.offline = True
            return OfflineProvider(model=f"offline-{self.model}")
        if isinstance(p, AnthropicProvider):
            p.model = self.model
        return p

    # -- completion ---------------------------------------------------------
    def complete(self, messages: list[dict], *, max_tokens: int = 1024) -> dict:
        self.calls.append(messages)
        if self.offline:
            resp = self._offline_complete(messages, max_tokens)
        else:
            provider = self._resolve_provider()
            resp = provider.complete(messages, max_tokens=max_tokens)
        self._record(messages, resp)
        return resp

    def _offline_complete(self, messages: List[Dict[str, Any]], max_tokens: int = 1024) -> Dict[str, Any]:
        last = messages[-1]["content"] if messages else ""
        return {
            "content": f"[offline:{self.model}] {last[:120]}",
            "model": self.model,
            "usage": {"input_tokens": _approx(messages), "output_tokens": 16},
        }

    async def _online_complete(self, messages: List[Dict[str, Any]], max_tokens: int = 1024) -> Dict[str, Any]:
        """Async real HTTP path (Anthropic Messages API) for callers running in
        an event loop."""
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMProviderError("ANTHROPIC_API_KEY not set")

        async with AsyncClient() as client:
            try:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                             "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={"model": self.model, "max_tokens": max_tokens,
                          "messages": messages},
                )
                response.raise_for_status()
                data = response.json()
                text = "".join(b.get("text", "") for b in data.get("content", []))
                resp = {"content": text, "model": data.get("model", self.model),
                        "usage": data.get("usage", {})}
                self._record(messages, resp)
                return resp
            except HTTPError as e:
                raise LLMProviderError(f"API call failed: {e}")
            except RequestError as e:
                raise LLMProviderError(f"Request error: {e}")

    def bulk_complete(self, messages: List[List[Dict[str, Any]]], *,
                      max_tokens: int = 1024) -> List[Dict[str, Any]]:
        """Complete a batch of conversations sequentially. Works in both offline
        and online modes; individual failures abort the batch with LLMBulkError
        naming the failing index."""
        out: List[Dict[str, Any]] = []
        for i, msgs in enumerate(messages):
            try:
                out.append(self.complete(msgs, max_tokens=max_tokens))
            except Exception as e:
                raise LLMBulkError(f"bulk_complete failed at index {i}: {e}") from e
        return out

    # -- history ------------------------------------------------------------
    def _record(self, messages: List[Dict[str, Any]], resp: Dict[str, Any]) -> None:
        rec = {
            "model": resp.get("model", self.model),
            "messages": messages,
            "response": resp.get("content", ""),
            "usage": resp.get("usage", {}),
            "offline": self.offline,
            "ts": time.time(),
        }
        self.history.append(rec)
        if self._history_db:
            with sqlite3.connect(self._history_db) as conn:
                conn.execute(
                    "INSERT INTO llm_history (model, messages, response, usage, offline, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (rec["model"], json.dumps(rec["messages"]), rec["response"],
                     json.dumps(rec["usage"]), int(rec["offline"]), rec["ts"]))

    def enable_history_db(self, path: str) -> None:
        """Persist every completion record to a SQLite db at `path`."""
        with sqlite3.connect(path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT, messages TEXT, response TEXT,
                    usage TEXT, offline INTEGER, ts REAL
                )""")
        self._history_db = path

    def query_history(self, filters: Dict[str, Any] | None = None,
                      limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Query past completions. Filters:
          model            exact match on model name
          offline          bool match
          content_contains substring match on prompt or response text
          since            minimum record timestamp (epoch seconds)
        Reads the SQLite store when enabled, else the in-memory history."""
        filters = filters or {}
        records = self._load_history_records()

        def keep(r: Dict[str, Any]) -> bool:
            if "model" in filters and r["model"] != filters["model"]:
                return False
            if "offline" in filters and bool(r["offline"]) != bool(filters["offline"]):
                return False
            if "since" in filters and r["ts"] < filters["since"]:
                return False
            if "content_contains" in filters:
                needle = str(filters["content_contains"]).lower()
                hay = (r["response"] + " " + " ".join(
                    m.get("content", "") for m in r["messages"])).lower()
                if needle not in hay:
                    return False
            return True

        matched = [r for r in records if keep(r)]
        return matched[offset:offset + limit]

    def _load_history_records(self) -> List[Dict[str, Any]]:
        if not self._history_db:
            return list(self.history)
        with sqlite3.connect(self._history_db) as conn:
            rows = conn.execute(
                "SELECT model, messages, response, usage, offline, ts "
                "FROM llm_history ORDER BY id").fetchall()
        return [{"model": m, "messages": json.loads(msgs), "response": resp,
                 "usage": json.loads(usage), "offline": bool(off), "ts": ts}
                for m, msgs, resp, usage, off, ts in rows]

    # -- (de)serialization ----------------------------------------------------
    def serialize_call(self, messages: List[Dict[str, Any]]) -> str:
        """Serialize a call as JSON: {'model': ..., 'messages': [...]}."""
        return json.dumps({"model": self.model, "messages": messages})

    @classmethod
    def deserialize_call(cls, serialized: str) -> Dict[str, Any]:
        """Parse a serialized call back into a dict. Strict JSON only — no
        template rendering of untrusted data."""
        data = json.loads(serialized)
        if not isinstance(data, dict) or "messages" not in data:
            raise ValueError("serialized call must be a JSON object with 'messages'")
        return data


def _approx(messages):
    return sum(len(m.get("content", "")) for m in messages) // 4


def _selftest():
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        c = LLMClient(offline=True)

        # offline completion is deterministic and honestly tagged
        r = c.complete([{"role": "user", "content": "hello there"}])
        assert r["content"].startswith("[offline:") and "hello there" in r["content"]
        assert r["usage"]["output_tokens"] == 16

        # bulk works offline (regression: it used to refuse offline mode and
        # return un-awaited coroutines online)
        rs = c.bulk_complete([[{"role": "user", "content": "a"}],
                              [{"role": "user", "content": "b"}]])
        assert len(rs) == 2 and all("content" in x for x in rs)

        # query_history is implemented (regression: NotImplementedError)
        h = c.query_history({"model": c.model})
        assert len(h) == 3
        h2 = c.query_history({"content_contains": "hello"})
        assert len(h2) == 1 and "hello there" in h2[0]["response"]
        assert c.query_history({"model": "other-model"}) == []
        assert len(c.query_history({}, limit=2)) == 2
        assert len(c.query_history({}, limit=10, offset=2)) == 1

        # sqlite persistence path
        db_path = f"{tmpdir}/history.db"
        c2 = LLMClient(offline=True)
        c2.enable_history_db(db_path)
        c2.complete([{"role": "user", "content": "persisted prompt"}])
        got = c2.query_history({"content_contains": "persisted"})
        assert len(got) == 1 and got[0]["offline"] is True
        # a fresh client reading the same db sees the record
        c3 = LLMClient(offline=True)
        c3.enable_history_db(db_path)
        assert len(c3.query_history({})) == 1

        # JSON round-trip (regression: jinja2 render + str-cast-to-Dict)
        blob = c.serialize_call([{"role": "user", "content": "x"}])
        back = LLMClient.deserialize_call(blob)
        assert isinstance(back, dict)
        assert back["messages"] == [{"role": "user", "content": "x"}]
        assert back["model"] == c.model
        try:
            LLMClient.deserialize_call('"just a string"')
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

        # provider delegation: a custom provider object is actually used
        class FakeProvider:
            offline = False
            model = "fake-1"

            def complete(self, messages, *, max_tokens=1024):
                return {"content": "FAKE", "model": self.model, "usage": {}}

        c4 = LLMClient(offline=False, provider=FakeProvider())
        assert c4.complete([{"role": "user", "content": "q"}])["content"] == "FAKE"

    print("llm_client selftest passed")


if __name__ == "__main__":
    _selftest()
