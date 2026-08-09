"""
streaming — Stream tokens to client via SSE.

### PART-META-JSON
{
  "name": "streaming",
  "layer": "ai",
  "purpose": "Generator-based token streaming utilities: chunked text streaming, SSE formatting, tokenizer-driven streaming (abstract Tokenizer plus concrete WhitespaceTokenizer/CharTokenizer defaults), retry/rate-limit/hook/cache/serializer wrappers around any stream function.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi",
    "pydantic"
  ],
  "inputs": "stream_text(text, chunk_size); sse_format(data, event); stream_with_retry(stream_func, max_retries, delay); stream_with_rate_limit(stream_func, rate_limit, interval); stream_text_with_tokens(text, tokenizer).",
  "outputs": "Generators yielding text chunks or SSE-formatted frames ('event: ...\\ndata: ...\\n\\n').",
  "files_created": [],
  "security_notes": "sse_format does not escape newlines inside data - callers streaming untrusted multi-line content must sanitize it or an attacker can forge SSE frames. stream_with_retry re-yields from the start on failure, so consumers may see duplicated leading chunks if a stream dies mid-way (documented at the function). Rate limiting sleeps in-process (blocking); use only in worker threads, not the event loop.",
  "ai_usage": "for frame in stream_from_generator(stream_text(answer), event='token'): send(frame).",
  "example": "from scrapyard.ai.streaming import stream_text, sse_format",
  "import_path": "scrapyard.ai.streaming"
}
### END-PART-META
"""
import abc
import time
from typing import Generator, Callable, Dict, Any, TypeVar, Generic, List
from fastapi import HTTPException
from pydantic import BaseModel

T = TypeVar('T')


class Tokenizer(abc.ABC, Generic[T]):
    """Abstract tokenizer contract; subclass and implement tokenize()."""

    @abc.abstractmethod
    def tokenize(self, text: str) -> List[str]:
        raise NotImplementedError()


class WhitespaceTokenizer(Tokenizer[str]):
    """Concrete default tokenizer: splits on whitespace."""

    def tokenize(self, text: str) -> List[str]:
        return (text or "").split()


class CharTokenizer(Tokenizer[str]):
    """Concrete tokenizer emitting one token per character."""

    def tokenize(self, text: str) -> List[str]:
        return list(text or "")


class Model(BaseModel):
    pass


def sse_format(data: str, event: str | None = None) -> str:
    prefix = f"event: {event}\n" if event else ""
    return prefix + f"data: {data}\n\n"


def stream_text(text: str, chunk_size: int = 20):
    """Yield a response in chunks (generator) — the basis for token streaming to an
    SSE/WebSocket transport without coupling to one."""
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


def stream_text_with_tokens(text: str, tokenizer: Tokenizer[str], chunk_size: int = 20) -> Generator[str, None, None]:
    tokens = tokenizer.tokenize(text)
    for i in range(0, len(tokens), chunk_size):
        yield '\n'.join(tokens[i:i + chunk_size])


def stream_from_generator(generator: Generator[str, None, None], chunk_size: int = 20, event: str | None = None) -> Generator[str, None, None]:
    for data in generator:
        yield sse_format(data, event=event)


def stream_with_hooks(stream_func: Callable[..., Generator[str, None, None]], hooks: Dict[str, Callable[[Any], Any]], **kwargs) -> Generator[str, None, None]:
    def run_hooks(hook_name: str):
        if hook_name in hooks:
            hooks[hook_name](**kwargs)

    for chunk in stream_func(**kwargs):
        run_hooks('pre_stream')
        yield chunk
        run_hooks('post_stream')


def sse_stream(data: str | Generator[str, None, None], event: str | None = None, chunk_size: int = 20, headers: Dict[str, str] | None = None) -> Generator[str, None, None]:
    if isinstance(data, str):
        data = stream_text(data, chunk_size=chunk_size)
    for chunk in data:
        yield sse_format(chunk, event=event)


def sse_stream_from_model(model: Model, input: str, event: str | None = None, chunk_size: int = 20) -> Generator[str, None, None]:
    """Stream a model input through a tokenizer. Uses the model's tokenizer when
    it provides one (a .tokenize method), else the whitespace default."""
    tokenizer = model if isinstance(model, Tokenizer) or hasattr(model, "tokenize") \
        else WhitespaceTokenizer()
    return stream_from_generator(
        stream_text_with_tokens(input, tokenizer, chunk_size=chunk_size),
        event=event)


def stream_with_retry(stream_func: Callable[..., Generator[str, None, None]], max_retries: int = 3, delay: float = 1.0) -> Generator[str, None, None]:
    """Retry a failing stream function up to max_retries times, sleeping `delay`
    between attempts. NOTE: on retry the stream restarts from the beginning, so
    a consumer that already received chunks will see them again — dedupe
    downstream if the stream can fail mid-flight."""
    for attempt in range(max_retries + 1):
        try:
            yield from stream_func()
            return
        except Exception as e:
            if attempt == max_retries:
                raise HTTPException(status_code=503, detail="Stream failed after retries") from e
            time.sleep(delay)


def stream_with_rate_limit(stream_func: Callable[..., Generator[str, None, None]], rate_limit: int = 100, interval: float = 1.0) -> Generator[str, None, None]:
    """Yield chunks at no more than rate_limit chunks per `interval` seconds,
    sleeping just enough to stay under the cap."""
    if rate_limit <= 0 or interval <= 0:
        raise ValueError("rate_limit and interval must be positive")
    per_chunk = interval / rate_limit
    start = time.monotonic()
    emitted = 0
    for chunk in stream_func():
        due = start + emitted * per_chunk
        now = time.monotonic()
        if now < due:
            time.sleep(due - now)
        yield chunk
        emitted += 1


def stream_with_serializer(stream_func: Callable[..., Generator[str, None, None]], serializer: Callable[[str], str]) -> Generator[str, None, None]:
    for chunk in stream_func():
        yield serializer(chunk)


def stream_with_cache(stream_func: Callable[..., Generator[str, None, None]], cache_key: str) -> Generator[str, None, None]:
    """Cache the fully-materialized stream per cache_key so repeated calls with
    the same key replay without re-running the source."""
    cached = _stream_cache.get(cache_key)
    if cached is None:
        cached = list(stream_func())
        _stream_cache[cache_key] = cached
    yield from cached


_stream_cache: Dict[str, List[str]] = {}


def _selftest():
    # basic chunking
    chunks = list(stream_text("abcdefghij", chunk_size=4))
    assert chunks == ["abcd", "efgh", "ij"]

    # SSE format
    assert sse_format("hi", event="tok") == "event: tok\ndata: hi\n\n"
    frames = list(sse_stream("hello world!", event="t", chunk_size=6))
    assert all(f.startswith("event: t\ndata: ") for f in frames)

    # concrete tokenizers work; ABC still enforces the contract
    ws = WhitespaceTokenizer()
    assert ws.tokenize("a b  c") == ["a", "b", "c"]
    assert CharTokenizer().tokenize("ab") == ["a", "b"]
    try:
        Tokenizer()  # abstract base class must not instantiate
        raise AssertionError("abstract Tokenizer must not instantiate")
    except TypeError:
        pass
    toks = list(stream_text_with_tokens("one two three four", ws, chunk_size=2))
    assert toks == ["one\ntwo", "three\nfour"]

    # sse_stream_from_model uses a real default tokenizer
    out = list(sse_stream_from_model(Model(), "alpha beta"))
    assert out and "alpha" in out[0]

    # retry: fails twice then succeeds (regression: time.sleep used to raise
    # AttributeError because datetime.time was imported instead of the module)
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("boom")
        yield "ok"

    got = list(stream_with_retry(flaky, max_retries=3, delay=0.01))
    assert got == ["ok"] and attempts["n"] == 3

    # retry: exhausted -> HTTPException 503
    def always_fails():
        raise RuntimeError("nope")
        yield  # pragma: no cover

    try:
        list(stream_with_retry(always_fails, max_retries=1, delay=0.0))
        raise AssertionError("expected HTTPException")
    except HTTPException as e:
        assert e.status_code == 503

    # rate limit: all chunks arrive, and pacing actually slows the stream
    t0 = time.monotonic()
    limited = list(stream_with_rate_limit(lambda: stream_text("x" * 12, 2),
                                          rate_limit=100, interval=0.6))
    elapsed = time.monotonic() - t0
    assert limited == ["xx"] * 6
    # 5 inter-chunk gaps of 6ms each = 30ms of pacing; allow generous OS jitter
    assert elapsed >= 0.015, "rate limiter should have paced the stream"
    try:
        list(stream_with_rate_limit(lambda: iter([]), rate_limit=0))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    # hooks fire around chunks
    seen = []
    hooked = list(stream_with_hooks(lambda: stream_text("abcd", 2),
                                    {"pre_stream": lambda **kw: seen.append("pre"),
                                     "post_stream": lambda **kw: seen.append("post")}))
    assert hooked == ["ab", "cd"] and seen == ["pre", "post", "pre", "post"]

    # serializer wrapper
    up = list(stream_with_serializer(lambda: stream_text("ab", 1), str.upper))
    assert up == ["A", "B"]

    # cache replays without re-running the source
    runs = {"n": 0}

    def source():
        runs["n"] += 1
        yield from stream_text("zz", 1)

    a = list(stream_with_cache(source, "k1"))
    b = list(stream_with_cache(source, "k1"))
    assert a == b == ["z", "z"] and runs["n"] == 1
    _stream_cache.clear()

    print("streaming selftest passed")


if __name__ == "__main__":
    _selftest()
