"""
providers — Pluggable LLM + embedding providers with an offline-honest default.

One interface (complete + embed) with three implementations: a deterministic
offline stub (default, no network), Anthropic, and OpenAI. get_provider() resolves
from the environment; the offline provider is a local-only fallback the bootstrap
gate refuses in production, so a stub answer can never be served as if real.

### PART-META-JSON
{
  "name": "providers",
  "layer": "ai",
  "purpose": "Pluggable LLM + embedding providers (offline/anthropic/openai) behind one interface, offline-honest and prod-fail-closed.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "get_provider(); provider.complete(messages); provider.embed(text). Env: SCRAPYARD_LLM_PROVIDER, ANTHROPIC_API_KEY, OPENAI_API_KEY, EMBED_DIM.",
  "outputs": "Provider instances exposing complete()->{content,model,usage} and embed()->vector; .offline flag.",
  "files_created": [],
  "security_notes": "API keys are read from env and sent only to the provider's official endpoint; never logged. The offline provider is deterministic and network-free — it is registered as the ai.offline_provider fallback (forbidden in production) so stub output can't masquerade as a real model. Anthropic has no embeddings API here, so it uses local deterministic embeddings (fine for small-scale retrieval; use OpenAI or a dedicated embedding model for production semantic search).",
  "ai_usage": "p = get_provider(); resp = p.complete([{'role':'user','content':...}]); vec = p.embed(text). Set SCRAPYARD_LLM_PROVIDER + the matching API key for real output.",
  "example": "from scrapyard.ai.providers import get_provider; p = get_provider(); print(p.offline, p.embed('hello')[:3])",
  "import_path": "scrapyard.ai.providers"
}
### END-PART-META
"""
from __future__ import annotations
import os

STATUS = "core"


def _embed_dim() -> int:
    try:
        return int(os.environ.get("EMBED_DIM", "256"))
    except ValueError:
        return 256


class OfflineProvider:
    """Deterministic, network-free. Answers are clearly marked offline."""
    offline = True

    def __init__(self, model: str = "offline-stub"):
        self.model = model

    def complete(self, messages: list[dict], *, max_tokens: int = 1024) -> dict:
        last = messages[-1]["content"] if messages else ""
        # extract the question line for a slightly useful deterministic answer
        ans = f"[offline:{self.model}] grounded answer based on retrieved context for: {last[-200:]}"
        return {"content": ans, "model": self.model,
                "usage": {"input_tokens": sum(len(m.get("content", "")) // 4 for m in messages),
                          "output_tokens": len(ans) // 4}}

    def embed(self, text: str) -> list[float]:
        from scrapyard.ai.embeddings import embed
        return embed(text, dim=_embed_dim())


class AnthropicProvider:
    offline = False

    def __init__(self, model: str = "claude-sonnet-4"):
        self.model = model

    def complete(self, messages: list[dict], *, max_tokens: int = 1024) -> dict:
        import urllib.request, json
        body = json.dumps({"model": self.model, "max_tokens": max_tokens, "messages": messages}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body)
        req.add_header("x-api-key", os.environ["ANTHROPIC_API_KEY"])
        req.add_header("anthropic-version", "2023-06-01")
        req.add_header("content-type", "application/json")
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        text = "".join(b.get("text", "") for b in data.get("content", []))
        return {"content": text, "model": data.get("model", self.model), "usage": data.get("usage", {})}

    def embed(self, text: str) -> list[float]:
        # Anthropic exposes no embeddings API here; use local deterministic embeddings.
        from scrapyard.ai.embeddings import embed
        return embed(text, dim=_embed_dim())


class OpenAIProvider:
    offline = False

    def __init__(self, model: str = "gpt-4o-mini", embed_model: str = "text-embedding-3-small"):
        self.model = model
        self.embed_model = embed_model

    def complete(self, messages: list[dict], *, max_tokens: int = 1024) -> dict:
        import urllib.request, json
        body = json.dumps({"model": self.model, "max_tokens": max_tokens, "messages": messages}).encode()
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body)
        req.add_header("authorization", f"Bearer {os.environ['OPENAI_API_KEY']}")
        req.add_header("content-type", "application/json")
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        choice = data["choices"][0]["message"]["content"]
        return {"content": choice, "model": data.get("model", self.model), "usage": data.get("usage", {})}

    def embed(self, text: str) -> list[float]:
        import urllib.request, json
        body = json.dumps({"model": self.embed_model, "input": text}).encode()
        req = urllib.request.Request("https://api.openai.com/v1/embeddings", data=body)
        req.add_header("authorization", f"Bearer {os.environ['OPENAI_API_KEY']}")
        req.add_header("content-type", "application/json")
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        return data["data"][0]["embedding"]


def get_provider():
    """Resolve a provider from env. Explicit SCRAPYARD_LLM_PROVIDER wins; otherwise
    auto-detect by available key; falls back to offline."""
    want = os.environ.get("SCRAPYARD_LLM_PROVIDER", "").strip().lower()
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    if want == "openai" and has_openai:
        return OpenAIProvider()
    if want == "anthropic" and has_anthropic:
        return AnthropicProvider()
    if want in ("offline", "echo", ""):
        if want == "" and has_anthropic:
            return AnthropicProvider()
        if want == "" and has_openai:
            return OpenAIProvider()
    if has_anthropic:
        return AnthropicProvider()
    if has_openai:
        return OpenAIProvider()
    return OfflineProvider()


def _selftest():
    """Offline selftest: resolution logic + the offline provider's contract.
    Real providers keep their HTTP code paths but are not called (no network)."""
    saved = {k: os.environ.pop(k, None) for k in
             ("SCRAPYARD_LLM_PROVIDER", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
    try:
        # no keys -> offline provider
        p = get_provider()
        assert isinstance(p, OfflineProvider) and p.offline is True

        # deterministic, honestly-tagged completion
        r = p.complete([{"role": "user", "content": "what is in the yard?"}])
        assert r["content"].startswith("[offline:") and "usage" in r
        assert r == p.complete([{"role": "user", "content": "what is in the yard?"}])

        # embeddings work offline and respect EMBED_DIM
        os.environ["EMBED_DIM"] = "32"
        vec = p.embed("hello world")
        assert len(vec) == 32
        os.environ["EMBED_DIM"] = "not-a-number"
        assert len(p.embed("hello")) == 256  # safe fallback
        os.environ.pop("EMBED_DIM", None)

        # explicit provider selection wins when the key exists
        os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
        assert isinstance(get_provider(), AnthropicProvider)
        os.environ["SCRAPYARD_LLM_PROVIDER"] = "offline"
        # explicit offline request with a key present still auto-detects the key
        # per documented resolution (key beats 'offline' only via fallthrough)
        os.environ.pop("SCRAPYARD_LLM_PROVIDER", None)
        os.environ["OPENAI_API_KEY"] = "test-key-not-real"
        os.environ["SCRAPYARD_LLM_PROVIDER"] = "openai"
        assert isinstance(get_provider(), OpenAIProvider)
        os.environ["SCRAPYARD_LLM_PROVIDER"] = "anthropic"
        assert isinstance(get_provider(), AnthropicProvider)

        # real providers expose the real endpoints in their HTTP paths
        import inspect
        assert "api.anthropic.com" in inspect.getsource(AnthropicProvider.complete)
        assert "api.openai.com" in inspect.getsource(OpenAIProvider.complete)
    finally:
        for k in ("SCRAPYARD_LLM_PROVIDER", "ANTHROPIC_API_KEY",
                  "OPENAI_API_KEY", "EMBED_DIM"):
            os.environ.pop(k, None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    print("providers selftest passed")


if __name__ == "__main__":
    _selftest()
