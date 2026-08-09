"""
local_llm_client — Standardized client for local LLM servers (Ollama and OpenAI-compatible endpoints): real HTTP inference when a server is configured, deterministic offline mode for tests.

### PART-META-JSON
{
  "name": "local_llm_client",
  "layer": "llm",
  "purpose": "Uniform interface to local LLM services: connect_local(provider, host, port) records the endpoint, send_local_request(prompt, model_name) POSTs to the real API (Ollama /api/generate, or /v1/completions for openai-compatible servers) and returns the generated text. offline=True (default until connected, and forced in the selftest) returns a deterministic tagged stub with zero network so tests never depend on a running server.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "requests"
  ],
  "inputs": "connect_local('ollama'|'openai-compatible', host, port); send_local_request(prompt, model_name, timeout=); client.offline flag.",
  "outputs": "Generated text string; offline mode returns '[offline-local:<model>] <prompt-head>' so stub output is unmistakable.",
  "files_created": [],
  "security_notes": "Requests go over plain HTTP to the configured host/port - local LLM servers are typically unauthenticated, so never point this at a host you don't control and never expose the port beyond localhost/LAN. Prompts are sent verbatim to that server. No API keys are involved and nothing is logged beyond endpoint metadata. Connection/HTTP failures raise RuntimeError rather than silently returning stub text.",
  "ai_usage": "c = LocalLLMClient(); c.connect_local('ollama', 'localhost', 11434); text = c.send_local_request('say hi', 'qwen3:30b').",
  "example": "from scrapyard.llm.local_llm_client import LocalLLMClient",
  "import_path": "scrapyard.llm.local_llm_client"
}
### END-PART-META
"""
import logging
from typing import Optional

from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LLMConnectionConfig:
    provider: str
    host: str
    port: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class LocalLLMClient:
    """Client for local LLM servers. Real HTTP path when connected; deterministic
    offline stub when offline=True (never silently — output is tagged)."""

    SUPPORTED_PROVIDERS = ("ollama", "openai-compatible")

    def __init__(self, *, offline: bool = False):
        self.config: Optional[LLMConnectionConfig] = None
        self.offline = offline

    def connect_local(self, provider: str, host: str, port: int) -> None:
        if not all([provider, host, port]):
            raise ValueError("Provider, host, and port must be specified.")
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'. "
                             f"Supported: {self.SUPPORTED_PROVIDERS}")
        self.config = LLMConnectionConfig(provider=provider, host=host, port=int(port))
        logger.info("Configured local LLM endpoint %s (%s)",
                    self.config.base_url, provider)

    def send_local_request(self, prompt: str, model_name: str,
                           timeout: float = 120.0) -> str:
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        if self.offline:
            # Deterministic offline mode: clearly tagged, zero network.
            return f"[offline-local:{model_name}] {prompt[:120]}"

        if self.config is None:
            raise RuntimeError("Not connected. Call connect_local() first "
                               "(or construct with offline=True for tests).")

        import requests
        try:
            if self.config.provider == "ollama":
                # Real Ollama generate API
                resp = requests.post(
                    f"{self.config.base_url}/api/generate",
                    json={"model": model_name, "prompt": prompt, "stream": False},
                    timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "")
            # openai-compatible local server (llama.cpp server, vLLM, LM Studio)
            resp = requests.post(
                f"{self.config.base_url}/v1/completions",
                json={"model": model_name, "prompt": prompt},
                timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0].get("text", "")
        except requests.RequestException as e:
            raise RuntimeError(
                f"Local LLM request to {self.config.base_url} failed: {e}") from e

    def is_available(self, timeout: float = 2.0) -> bool:
        """Probe the configured server (Ollama exposes /api/tags)."""
        if self.offline or self.config is None:
            return False
        import requests
        try:
            url = (f"{self.config.base_url}/api/tags"
                   if self.config.provider == "ollama"
                   else f"{self.config.base_url}/v1/models")
            return requests.get(url, timeout=timeout).ok
        except requests.RequestException:
            return False


def _selftest() -> None:
    # offline mode: deterministic, tagged, no network
    client = LocalLLMClient(offline=True)
    out = client.send_local_request("What is the weather like?", "weather_model")
    assert out.startswith("[offline-local:weather_model]")
    assert "What is the weather" in out
    assert out == client.send_local_request("What is the weather like?", "weather_model")

    # config validation
    client2 = LocalLLMClient(offline=True)
    client2.connect_local(provider="ollama", host="localhost", port=11434)
    assert client2.config is not None
    assert client2.config.base_url == "http://localhost:11434"
    try:
        client2.connect_local(provider="banana", host="localhost", port=1)
        raise AssertionError("expected ValueError for unsupported provider")
    except ValueError:
        pass
    try:
        client2.connect_local(provider="ollama", host="", port=1)
        raise AssertionError("expected ValueError for missing host")
    except ValueError:
        pass

    # empty prompt rejected in both modes
    try:
        client.send_local_request("   ", "m")
        raise AssertionError("expected ValueError for empty prompt")
    except ValueError:
        pass

    # online mode without connection fails loudly instead of faking output
    disconnected = LocalLLMClient()
    assert disconnected.offline is False
    try:
        disconnected.send_local_request("hi", "m")
        raise AssertionError("expected RuntimeError when not connected")
    except RuntimeError:
        pass

    # availability probe is False offline (no network touched)
    assert client2.is_available() is False  # offline=True short-circuits

    # the real HTTP paths exist and target the documented endpoints
    import inspect
    src = inspect.getsource(LocalLLMClient.send_local_request)
    assert "/api/generate" in src and "/v1/completions" in src

    logger.info("Self-test completed successfully.")
    print("local_llm_client selftest passed")


if __name__ == "__main__":
    _selftest()
