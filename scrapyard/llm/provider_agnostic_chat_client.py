"""
provider_agnostic_chat_client — Provider-agnostic chat client: one Conversation/Response interface over Anthropic, OpenAI, offline, and a deterministic local provider, with per-conversation history and streaming hooks.

### PART-META-JSON
{
  "name": "provider_agnostic_chat_client",
  "layer": "llm",
  "purpose": "Chat client abstraction usable with multiple LLM backends: start_conversation(provider, config) builds a Conversation bound to 'anthropic', 'openai', 'offline', or 'local' (deterministic echo for tests); handle_message() sends user input through the bound provider, appends to the conversation history, and returns a Response with metadata. Real providers delegate to scrapyard.ai.providers (live HTTPS when keys are configured).",
  "addition": true,
  "status": "core",
  "dependencies": [
    "scrapyard.ai.providers"
  ],
  "inputs": "start_conversation('anthropic'|'openai'|'offline'|'local', {'model': ...}); handle_message(conv, text); conv.state['history'].",
  "outputs": "Conversation (id, provider, state incl. history) and Response (text, metadata with model/usage).",
  "files_created": [],
  "security_notes": "API keys are read from env by scrapyard.ai.providers and sent only to official provider endpoints; this module never logs them. Conversation history is kept in process memory (state['history']) including full user inputs - do not put secrets in messages you later serialize. The 'local' and 'offline' providers are deterministic and clearly distinguishable from live model output (offline responses carry the '[offline:' tag; local echoes).",
  "ai_usage": "conv = start_conversation('offline', {}); r = handle_message(conv, 'hi'); print(r.text).",
  "example": "from scrapyard.llm.provider_agnostic_chat_client import start_conversation, handle_message",
  "import_path": "scrapyard.llm.provider_agnostic_chat_client"
}
### END-PART-META
"""
from typing import Dict, Any, List, Optional
import abc
import itertools
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_conversation_ids = itertools.count(1)


@dataclass
class Conversation:
    id: int
    provider: str
    state: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Response:
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """Provider contract: build with a config dict, generate responses."""

    def __init__(self, config: dict):
        self.config = dict(config or {})

    @abc.abstractmethod
    def generate_response(self, prompt: str) -> Response:
        raise NotImplementedError


class LocalLLMClient(LLMProvider):
    """Deterministic local provider for offline tests: echoes the prompt. Kept
    intentionally simple so selftests have a fully predictable backend."""

    def __init__(self, config: dict):
        super().__init__(config)

    def generate_response(self, prompt: str) -> Response:
        return Response(text="Local response to " + prompt,
                        metadata={"model": self.config.get("model", "local-echo"),
                                  "provider": "local"})


class _ProvidersBackedClient(LLMProvider):
    """Base for providers implemented via scrapyard.ai.providers."""
    provider_key = "offline"

    def _provider(self):
        from scrapyard.ai import providers as P
        if self.provider_key == "anthropic":
            return P.AnthropicProvider(model=self.config.get("model", "claude-sonnet-4"))
        if self.provider_key == "openai":
            return P.OpenAIProvider(model=self.config.get("model", "gpt-4o-mini"))
        return P.OfflineProvider(model=self.config.get("model", "offline-stub"))

    def generate_response(self, prompt: str) -> Response:
        raw = self._provider().complete(
            [{"role": "user", "content": prompt}],
            max_tokens=int(self.config.get("max_tokens", 1024)))
        return Response(text=raw["content"],
                        metadata={"model": raw.get("model"),
                                  "usage": raw.get("usage", {}),
                                  "provider": self.provider_key})


class OfflineChatProvider(_ProvidersBackedClient):
    provider_key = "offline"


class AnthropicChatProvider(_ProvidersBackedClient):
    """Real Anthropic Messages API path (requires ANTHROPIC_API_KEY)."""
    provider_key = "anthropic"


class OpenAIChatProvider(_ProvidersBackedClient):
    """Real OpenAI chat completions path (requires OPENAI_API_KEY)."""
    provider_key = "openai"


class StreamHandler:
    """Streaming observer: on_message is called per emitted chunk."""

    def __init__(self):
        self.messages: List[str] = []

    def on_message(self, message: str):
        if not isinstance(message, str):
            raise TypeError("stream message must be a string")
        self.messages.append(message)
        return message


_PROVIDERS = {
    "local": LocalLLMClient,
    "offline": OfflineChatProvider,
    "anthropic": AnthropicChatProvider,
    "openai": OpenAIChatProvider,
}


def start_conversation(provider: str, config: dict) -> Conversation:
    provider_cls = _PROVIDERS.get(provider)
    if provider_cls is None:
        raise ValueError(f"Unsupported LLM provider: {provider}")
    llm_provider = provider_cls(config)
    return Conversation(id=next(_conversation_ids), provider=provider,
                        state={"llm": llm_provider, "history": []})


def handle_message(conv: Conversation, user_input: str,
                   stream_handler: Optional[StreamHandler] = None) -> Response:
    if not conv.state.get("llm"):
        raise ValueError("LLM provider is not initialized")

    response = conv.state["llm"].generate_response(user_input)
    conv.state["history"].append({"role": "user", "content": user_input})
    conv.state["history"].append({"role": "assistant", "content": response.text})
    if stream_handler is not None:
        # stream the response in small chunks through the handler
        for i in range(0, len(response.text), 20):
            stream_handler.on_message(response.text[i:i + 20])
    return response


def get_history(conv: Conversation) -> List[Dict[str, str]]:
    return list(conv.state.get("history", []))


def _selftest():
    # local deterministic provider
    conversation = start_conversation(provider="local", config={"model": "dummy"})
    assert isinstance(conversation, Conversation)

    response = handle_message(conversation, "Hello")
    assert isinstance(response, Response)
    assert response.text.startswith("Local response to Hello")
    assert response.metadata["provider"] == "local"

    # history accumulates for real
    handle_message(conversation, "Second message")
    hist = get_history(conversation)
    assert len(hist) == 4
    assert hist[0] == {"role": "user", "content": "Hello"}
    assert hist[3]["role"] == "assistant"

    # conversation ids are unique
    c2 = start_conversation(provider="local", config={})
    assert c2.id != conversation.id

    # offline provider goes through the shared providers layer, clearly tagged
    off = start_conversation(provider="offline", config={"model": "stub-model"})
    r = handle_message(off, "what parts exist?")
    assert r.text.startswith("[offline:") and "usage" in r.metadata

    # real providers are registered with real HTTP paths (not called offline)
    assert set(_PROVIDERS) == {"local", "offline", "anthropic", "openai"}
    import inspect
    from scrapyard.ai import providers as P
    assert "api.anthropic.com" in inspect.getsource(P.AnthropicProvider.complete)
    assert "api.openai.com" in inspect.getsource(P.OpenAIProvider.complete)

    # streaming hook receives the chunks
    chunks = []

    base_handler = StreamHandler()
    assert base_handler.on_message("one") == "one"
    assert base_handler.messages == ["one"]
    try:
        base_handler.on_message(1)
        raise AssertionError("accepted a non-string stream message")
    except TypeError:
        pass

    class Collect(StreamHandler):
        def on_message(self, message: str):
            chunks.append(message)

    handle_message(conversation, "stream me a long enough response please",
                   stream_handler=Collect())
    assert "".join(chunks).startswith("Local response to stream me")

    # unsupported provider rejected
    try:
        start_conversation(provider="martian", config={})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    # uninitialized conversation rejected
    try:
        handle_message(Conversation(id=0, provider="x", state={}), "hi")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    logger.info("Self-test completed successfully")
    print("provider_agnostic_chat_client selftest passed")


if __name__ == "__main__":
    _selftest()
