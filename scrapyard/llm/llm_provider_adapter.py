"""
llm_provider_adapter — Adapter layer unifying LLM provider APIs: one request/response shape routed via ModelRouter to real Anthropic, OpenAI, or offline adapters backed by scrapyard.ai.providers.

### PART-META-JSON
{
  "name": "llm_provider_adapter",
  "layer": "llm",
  "purpose": "Unified adapter interface over LLM providers: adapt_request() translates a provider-neutral request ({text|messages, max_tokens}) into each provider's wire format, translate_response() normalizes each provider's response into {output, model, usage, status}, and complete() executes the call through scrapyard.ai.providers (real HTTPS when API keys are configured, deterministic offline adapter otherwise). ModelRouter resolves adapters by name, with legacy 'provider1'/'provider2' aliases kept for API stability.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "scrapyard.ai.providers"
  ],
  "inputs": "ModelRouter().select_provider('anthropic'|'openai'|'offline'|'provider1'|'provider2'); adapter.adapt_request({'text': ...}|{'messages': [...]}); adapter.translate_response(raw); adapter.complete(request).",
  "outputs": "adapt_request -> provider wire-format dict; translate_response -> {output, model, usage, status}; complete -> translated response from the live provider (offline adapter returns a clearly-tagged deterministic stub).",
  "files_created": [],
  "security_notes": "Real calls go through scrapyard.ai.providers, which reads ANTHROPIC_API_KEY/OPENAI_API_KEY from env and sends them only to the providers' official HTTPS endpoints; this module never touches or logs keys itself. The offline adapter's output is prefixed '[offline:' so stub responses cannot be mistaken for model output. translate_response validates the response shape and raises ValueError on malformed payloads instead of fabricating fields.",
  "ai_usage": "router = ModelRouter(); a = router.select_provider('anthropic')['adapter']; body = a.adapt_request({'text': 'hi'}); resp = a.complete({'text': 'hi'}).",
  "example": "from scrapyard.llm.llm_provider_adapter import ModelRouter",
  "import_path": "scrapyard.llm.llm_provider_adapter"
}
### END-PART-META
"""

from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


def _to_messages(request: Dict[str, Any]) -> List[Dict[str, str]]:
    """Accept {'messages': [...]} or {'text': str} and return chat messages."""
    if "messages" in request:
        msgs = request["messages"]
        if not isinstance(msgs, list) or not all(
                isinstance(m, dict) and "role" in m and "content" in m for m in msgs):
            raise ValueError("messages must be a list of {role, content} dicts")
        return msgs
    if "text" in request:
        return [{"role": "user", "content": str(request["text"])}]
    raise ValueError("request must contain 'text' or 'messages'")


class BaseAdapter:
    """Adapter contract: request adaptation, response translation, execution."""
    provider_name = "base"

    def adapt_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def translate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def _provider(self):
        raise NotImplementedError

    def complete(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Adapt, execute against the real provider, translate back."""
        messages = _to_messages(request)
        max_tokens = int(request.get("max_tokens", 1024))
        raw = self._provider().complete(messages, max_tokens=max_tokens)
        # providers.py already normalizes to {content, model, usage}
        return {"output": raw["content"], "model": raw.get("model"),
                "usage": raw.get("usage", {}), "status": "success"}


class AnthropicAdapter(BaseAdapter):
    """Adapts the unified shape to the Anthropic Messages API."""
    provider_name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4"):
        self.model = model

    def adapt_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {"model": request.get("model", self.model),
                "max_tokens": int(request.get("max_tokens", 1024)),
                "messages": _to_messages(request)}

    def translate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Translate a raw Anthropic Messages API response body."""
        if not isinstance(response, dict) or "content" not in response:
            raise ValueError("malformed Anthropic response: missing 'content'")
        blocks = response["content"]
        if isinstance(blocks, list):
            text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
        else:
            text = str(blocks)
        return {"output": text, "model": response.get("model", self.model),
                "usage": response.get("usage", {}), "status": "success"}

    def _provider(self):
        from scrapyard.ai.providers import AnthropicProvider
        return AnthropicProvider(model=self.model)


class OpenAIAdapter(BaseAdapter):
    """Adapts the unified shape to the OpenAI chat completions API."""
    provider_name = "openai"

    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model

    def adapt_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {"model": request.get("model", self.model),
                "max_tokens": int(request.get("max_tokens", 1024)),
                "messages": _to_messages(request)}

    def translate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Translate a raw OpenAI chat completions response body."""
        if not isinstance(response, dict) or "choices" not in response \
                or not response["choices"]:
            raise ValueError("malformed OpenAI response: missing 'choices'")
        text = response["choices"][0].get("message", {}).get("content", "")
        return {"output": text, "model": response.get("model", self.model),
                "usage": response.get("usage", {}), "status": "success"}

    def _provider(self):
        from scrapyard.ai.providers import OpenAIProvider
        return OpenAIProvider(model=self.model)


class OfflineAdapter(BaseAdapter):
    """Deterministic offline adapter for tests/dev — output is clearly tagged."""
    provider_name = "offline"

    def __init__(self, model: str = "offline-stub"):
        self.model = model

    def adapt_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {"model": self.model,
                "max_tokens": int(request.get("max_tokens", 1024)),
                "messages": _to_messages(request)}

    def translate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(response, dict) or "content" not in response:
            raise ValueError("malformed offline response: missing 'content'")
        return {"output": response["content"],
                "model": response.get("model", self.model),
                "usage": response.get("usage", {}), "status": "success"}

    def _provider(self):
        from scrapyard.ai.providers import OfflineProvider
        return OfflineProvider(model=self.model)


# Legacy aliases kept for API stability: the old Provider1Adapter/Provider2Adapter
# fabricated responses; they are now thin names over the real adapters.
class Provider1Adapter(AnthropicAdapter):
    pass


class Provider2Adapter(OpenAIAdapter):
    pass


class ModelRouter:
    def __init__(self):
        self.providers = {
            "anthropic": {"adapter": AnthropicAdapter()},
            "openai": {"adapter": OpenAIAdapter()},
            "offline": {"adapter": OfflineAdapter()},
            # legacy names route to the real adapters
            "provider1": {"adapter": Provider1Adapter()},
            "provider2": {"adapter": Provider2Adapter()},
        }

    def select_provider(self, provider: str) -> Optional[Dict[str, Any]]:
        return self.providers.get(provider)


def adapt_request(provider: str, request: Dict[str, Any]) -> Dict[str, Any]:
    entry = ModelRouter().select_provider(provider)
    if not entry:
        raise ValueError(f"Provider {provider} is not supported")
    return entry["adapter"].adapt_request(request)


def translate_response(provider: str, response: Dict[str, Any]) -> Dict[str, Any]:
    entry = ModelRouter().select_provider(provider)
    if not entry:
        raise ValueError(f"Provider {provider} is not supported")
    return entry["adapter"].translate_response(response)


def _selftest():
    router = ModelRouter()

    # adapt_request produces each provider's real wire shape
    a = router.select_provider("anthropic")["adapter"]
    body = a.adapt_request({"text": "Hello, world!", "max_tokens": 64})
    assert body == {"model": "claude-sonnet-4", "max_tokens": 64,
                    "messages": [{"role": "user", "content": "Hello, world!"}]}

    o = router.select_provider("openai")["adapter"]
    body2 = o.adapt_request({"messages": [{"role": "user", "content": "Hi"}]})
    assert body2["model"] == "gpt-4o-mini" and body2["messages"][0]["content"] == "Hi"

    # translate_response handles each provider's REAL response schema
    anthropic_raw = {"content": [{"type": "text", "text": "Greetings"}],
                     "model": "claude-sonnet-4",
                     "usage": {"input_tokens": 3, "output_tokens": 2}}
    t = a.translate_response(anthropic_raw)
    assert t == {"output": "Greetings", "model": "claude-sonnet-4",
                 "usage": {"input_tokens": 3, "output_tokens": 2},
                 "status": "success"}

    openai_raw = {"choices": [{"message": {"content": "Hi there"}}],
                  "model": "gpt-4o-mini", "usage": {"total_tokens": 5}}
    t2 = o.translate_response(openai_raw)
    assert t2["output"] == "Hi there" and t2["status"] == "success"

    # malformed responses are rejected, not fabricated
    for adapter, bad in ((a, {}), (o, {"choices": []})):
        try:
            adapter.translate_response(bad)
            raise AssertionError("expected ValueError on malformed response")
        except ValueError:
            pass

    # offline adapter executes end-to-end without network
    off = router.select_provider("offline")["adapter"]
    resp = off.complete({"text": "what is in the scrapyard?"})
    assert resp["status"] == "success" and resp["output"].startswith("[offline:")
    assert "usage" in resp

    # legacy provider1/provider2 names still resolve (to real adapters now)
    p1 = router.select_provider("provider1")["adapter"]
    assert isinstance(p1, AnthropicAdapter)
    p2 = router.select_provider("provider2")["adapter"]
    assert isinstance(p2, OpenAIAdapter)
    assert p1.adapt_request({"text": "x"})["messages"][0]["content"] == "x"

    # module-level helpers + unknown provider error
    assert adapt_request("offline", {"text": "y"})["messages"][0]["content"] == "y"
    try:
        adapt_request("nope", {"text": "z"})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    # invalid request shape
    try:
        a.adapt_request({"neither": True})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    print("llm_provider_adapter selftest passed")


if __name__ == "__main__":
    _selftest()
