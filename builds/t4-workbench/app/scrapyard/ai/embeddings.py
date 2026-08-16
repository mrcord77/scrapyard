"""
embeddings — Create + cache text embeddings.

### PART-META-JSON
{
  "name": "embeddings",
  "layer": "ai",
  "purpose": "Deterministic local text embeddings (hashed bag-of-tokens, L2-normalized) with an in-process cache, a correct cosine() for arbitrary (signed, unnormalized) vectors, and a real OpenAI embeddings HTTP path in embed_remote() used when OPENAI_API_KEY is configured.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "embed(text, dim=64); cosine(a, b); embed_remote(text, model=...) with env OPENAI_API_KEY; clear_cache().",
  "outputs": "embed -> L2-normalized List[float]; cosine -> float in [-1, 1]; embed_remote -> provider embedding vector.",
  "files_created": [],
  "security_notes": "Local embeddings are deterministic and network-free - suitable for tests and small-scale retrieval, not a substitute for a learned model in production semantic search. embed_remote() sends the text to api.openai.com over HTTPS using OPENAI_API_KEY from env (key is never logged); do not pass sensitive text unless that egress is acceptable. The cache is unbounded per process - call clear_cache() in long-running services with high-cardinality inputs.",
  "ai_usage": "from scrapyard.ai.embeddings import embed, cosine; sim = cosine(embed(a), embed(b)).",
  "example": "from scrapyard.ai.embeddings import embed, cosine",
  "import_path": "scrapyard.ai.embeddings"
}
### END-PART-META
"""
from __future__ import annotations
import hashlib, math, os

STATUS = "core"

_cache: dict[tuple[str, int], list[float]] = {}


def embed(text: str, dim: int = 64) -> list[float]:
    """Deterministic local embedding (hashed bag-of-tokens, L2-normalized). Good for
    tests/dev and small-scale similarity; swap embed_remote() for a real model.
    Results are cached per (text, dim)."""
    key = (text or "", dim)
    hit = _cache.get(key)
    if hit is not None:
        return list(hit)
    vec = [0.0] * dim
    for tok in (text or "").lower().split():
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    vec = [v / norm for v in vec]
    _cache[key] = list(vec)
    return vec


def clear_cache() -> int:
    """Drop all cached embeddings; returns how many entries were dropped."""
    n = len(_cache)
    _cache.clear()
    return n


def cosine(a: list[float], b: list[float]) -> float:
    """True cosine similarity for arbitrary vectors: dot/(|a||b|), in [-1, 1].
    Zero vectors (or empty input) score 0.0. For already-normalized vectors this
    equals the plain dot product the previous implementation assumed."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def embed_remote(text: str, model: str = "text-embedding-3-small") -> list[float]:
    """Real remote embedding via the OpenAI embeddings API (HTTPS). Requires
    OPENAI_API_KEY in the environment; raises RuntimeError when unconfigured so
    callers can fall back to the local embed()."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("no embedding provider configured: set OPENAI_API_KEY "
                           "to use remote embeddings, or use embed() locally")
    import json, urllib.request
    body = json.dumps({"model": model, "input": text}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/embeddings", data=body)
    req.add_header("authorization", f"Bearer {api_key}")
    req.add_header("content-type", "application/json")
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    return data["data"][0]["embedding"]


def _selftest():
    # deterministic + normalized
    a = embed("red apple fruit")
    assert embed("red apple fruit") == a
    assert abs(math.sqrt(sum(v * v for v in a)) - 1.0) < 1e-9

    # cache actually hits
    clear_cache()
    embed("hello world")
    assert ("hello world", 64) in _cache
    assert clear_cache() >= 1

    # shared tokens -> higher similarity
    sim_close = cosine(embed("red apple"), embed("green apple"))
    sim_far = cosine(embed("red apple"), embed("diesel engine"))
    assert sim_close > sim_far

    # cosine correctness on unnormalized / signed / zero vectors
    assert abs(cosine([2.0, 0.0], [4.0, 0.0]) - 1.0) < 1e-9
    assert abs(cosine([1.0, 0.0], [-1.0, 0.0]) + 1.0) < 1e-9
    assert cosine([1.0, 1.0], [1.0, -1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 2.0]) == 0.0
    assert cosine([], [1.0]) == 0.0

    # empty text embeds to zero vector without crashing
    z = embed("", 8)
    assert z == [0.0] * 8

    # remote path fails closed without a key (no network in selftest)
    had = os.environ.pop("OPENAI_API_KEY", None)
    try:
        embed_remote("x")
        raise AssertionError("expected RuntimeError without OPENAI_API_KEY")
    except RuntimeError:
        pass
    finally:
        if had is not None:
            os.environ["OPENAI_API_KEY"] = had

    print("embeddings selftest passed")


if __name__ == "__main__":
    _selftest()
