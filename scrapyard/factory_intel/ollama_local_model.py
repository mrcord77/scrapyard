"""
ollama_local_model — Real Ollama HTTP client (embeddings + generation) with a
deterministic offline fallback.

### PART-META-JSON
{
  "name": "ollama_local_model",
  "layer": "factory_intel",
  "purpose": "HTTP client for a local Ollama server (POST /api/embeddings and /api/generate via httpx) with a deterministic offline embedding fallback (hashed-token TF vector) used when Ollama is unreachable and by the selftest.",
  "addition": true,
  "status": "core",
  "dependencies": ["httpx"],
  "inputs": "Text strings/prompts; model name and endpoint from OllamaConfig (env: OLLAMA_ENDPOINT, OLLAMA_EMBED_MODEL, OLLAMA_GEN_MODEL).",
  "outputs": "Embedding vectors (list[float]); generated text; offline fallback vectors are deterministic per input text.",
  "files_created": [],
  "security_notes": "Talks only to the configured endpoint (default http://localhost:11434); never sends data to third parties. Offline mode performs no network I/O at all. Prompts/responses are not logged above DEBUG. Selftest is fully offline (offline=True), no live Ollama required.",
  "ai_usage": "client = OllamaClient(OllamaConfig(embed_model='nomic-embed-text')); vec = client.get_embedding(text). Module-level get_embedding(text) keeps the old signature. Pass offline=True (or set config.offline) to force the deterministic local vector.",
  "example": "from scrapyard.factory_intel.ollama_local_model import OllamaClient, OllamaConfig, get_embedding",
  "import_path": "scrapyard.factory_intel.ollama_local_model"
}
### END-PART-META
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

STATUS = "core"

DEFAULT_ENDPOINT = "http://localhost:11434"
OFFLINE_DIM = 256


@dataclass
class OllamaConfig:
    endpoint: str = field(default_factory=lambda: os.environ.get("OLLAMA_ENDPOINT", DEFAULT_ENDPOINT))
    embed_model: str = field(default_factory=lambda: os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
    gen_model: str = field(default_factory=lambda: os.environ.get("OLLAMA_GEN_MODEL", "qwen3:0.6b"))
    timeout: float = 60.0
    offline: bool = False          # force the deterministic local fallback
    fallback_to_offline: bool = True  # fall back if the server is unreachable


@dataclass
class OllamaModel:
    """Back-compat model descriptor."""
    model_name: str
    endpoint: str = DEFAULT_ENDPOINT

    def __post_init__(self):
        if not self.model_name:
            raise ValueError("Model name must be provided")


class OllamaUnavailableError(RuntimeError):
    pass


def offline_embedding(text: str, dim: int = OFFLINE_DIM) -> List[float]:
    """Deterministic hashed-token TF vector, L2-normalized. No network, no model.

    Same text -> same vector; token overlap -> cosine similarity. Used when
    Ollama is unreachable and by the offline selftest.
    """
    vec = [0.0] * dim
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    for tok in tokens:
        idx = int(hashlib.sha256(tok.encode()).hexdigest(), 16) % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class OllamaClient:
    """Real HTTP client for a local Ollama server, with offline fallback."""

    def __init__(self, config: Optional[OllamaConfig] = None):
        self.config = config or OllamaConfig()

    # -- HTTP ---------------------------------------------------------------
    def _post(self, path: str, payload: dict) -> dict:
        import httpx  # lazy so offline use never needs it at import time
        url = self.config.endpoint.rstrip("/") + path
        resp = httpx.post(url, json=payload, timeout=self.config.timeout)
        resp.raise_for_status()
        return resp.json()

    def is_available(self) -> bool:
        """True if the Ollama server answers. Never raises."""
        if self.config.offline:
            return False
        try:
            import httpx
            resp = httpx.get(self.config.endpoint.rstrip("/") + "/api/tags", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    # -- embeddings ---------------------------------------------------------
    def get_embedding(self, text: str, model: Optional[str] = None) -> List[float]:
        """POST /api/embeddings. Falls back to the deterministic offline vector
        when offline mode is set or the server is unreachable (if allowed)."""
        if self.config.offline:
            return offline_embedding(text)
        try:
            data = self._post("/api/embeddings",
                              {"model": model or self.config.embed_model, "prompt": text})
            emb = data.get("embedding")
            if not isinstance(emb, list) or not emb:
                raise OllamaUnavailableError(f"malformed embedding response: {data!r}")
            return [float(x) for x in emb]
        except OllamaUnavailableError:
            raise
        except Exception as e:
            if self.config.fallback_to_offline:
                logger.warning("Ollama unreachable (%s); using offline embedding", e)
                return offline_embedding(text)
            raise OllamaUnavailableError(f"Ollama embeddings failed: {e}") from e

    # -- generation ---------------------------------------------------------
    def generate(self, prompt: str, model: Optional[str] = None,
                 system: Optional[str] = None, **options) -> str:
        """POST /api/generate (non-streaming). Raises OllamaUnavailableError offline."""
        if self.config.offline:
            raise OllamaUnavailableError(
                "generation requires a live Ollama server (offline mode set)")
        payload = {"model": model or self.config.gen_model,
                   "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options
        try:
            data = self._post("/api/generate", payload)
        except Exception as e:
            raise OllamaUnavailableError(f"Ollama generate failed: {e}") from e
        return str(data.get("response", ""))


def get_embedding(text: str, model_name: Optional[str] = None,
                  offline: bool = False) -> List[float]:
    """Module-level convenience keeping the original signature.

    Real Ollama call when the server is up; deterministic offline vector otherwise.
    """
    cfg = OllamaConfig(offline=offline)
    if model_name:
        cfg.embed_model = model_name
    return OllamaClient(cfg).get_embedding(text)


def _selftest() -> bool:
    """Fully offline: exercises the deterministic fallback and client wiring."""
    # deterministic + normalized
    a1 = offline_embedding("the quick brown fox")
    a2 = offline_embedding("the quick brown fox")
    b = offline_embedding("completely different words entirely")
    assert a1 == a2 and len(a1) == OFFLINE_DIM
    assert all(isinstance(x, float) for x in a1)
    norm = math.sqrt(sum(x * x for x in a1))
    assert abs(norm - 1.0) < 1e-9, norm

    # similar texts closer than dissimilar ones
    def cos(u, v):
        return sum(x * y for x, y in zip(u, v))
    sim_close = cos(a1, offline_embedding("the quick brown fox jumps"))
    sim_far = cos(a1, b)
    assert sim_close > sim_far, (sim_close, sim_far)

    # client in offline mode: no network I/O
    client = OllamaClient(OllamaConfig(offline=True))
    v = client.get_embedding("hello world")
    assert v == offline_embedding("hello world")
    assert client.is_available() is False
    try:
        client.generate("hi")
        raise AssertionError("generate must not run offline")
    except OllamaUnavailableError:
        pass

    # module-level back-compat path (offline)
    v2 = get_embedding("hello world", offline=True)
    assert v2 == v

    # unreachable endpoint with fallback allowed -> offline vector, no crash
    cfg = OllamaConfig(endpoint="http://127.0.0.1:1", timeout=0.2)
    v3 = OllamaClient(cfg).get_embedding("hello world")
    assert v3 == offline_embedding("hello world")
    # ...and with fallback disabled -> informative error
    cfg2 = OllamaConfig(endpoint="http://127.0.0.1:1", timeout=0.2, fallback_to_offline=False)
    try:
        OllamaClient(cfg2).get_embedding("x")
        raise AssertionError("expected OllamaUnavailableError")
    except OllamaUnavailableError:
        pass

    # back-compat dataclass
    m = OllamaModel(model_name="test_model")
    assert m.model_name == "test_model"
    try:
        OllamaModel(model_name="")
        raise AssertionError("empty model accepted")
    except ValueError:
        pass

    print("ollama_local_model selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
