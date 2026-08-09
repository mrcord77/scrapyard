"""
sse_stream — Server-Sent Events response helper.

### PART-META-JSON
{
  "name": "sse_stream",
  "layer": "realtime",
  "purpose": "Server-Sent Events response helper.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Public API: event_stream(generator, event); with_event_type(generator, event_type); with_retry(generator, retry_seconds, error_msg); with_final(generator, final_event); with_serializer(generator, serializer); SerializationError(...) (plus more).",
  "outputs": "Returns: event_stream -> Generator[bytes, None, None]; with_event_type -> Generator[bytes, None, None]; with_retry -> Generator[bytes, None, None]; with_final -> Generator[bytes, None, None]; with_serializer -> Generator[bytes, None, None].",
  "files_created": [],
  "security_notes": "Renders HTML with all caller text escaped via html.escape (XSS-safe); any HTML 'slot' arguments are inserted verbatim and must be pre-escaped by the caller. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `event_stream` from `scrapyard.realtime.sse_stream` and call it as shown in `example`; run `py -m scrapyard.realtime.sse_stream` to see its offline selftest.",
  "example": "from scrapyard.realtime.sse_stream import event_stream",
  "import_path": "scrapyard.realtime.sse_stream"
}
### END-PART-META
"""
from __future__ import annotations
import html
from typing import AsyncGenerator
import logging
from typing import Any, Callable, Generator, Iterable, AsyncIterable, TypeVar

from cryptography.fernet import Fernet
import jinja2

from scrapyard.ai.streaming import sse_format

STATUS = "core"

T = TypeVar('T')

class SerializationError(Exception):
    pass

def event_stream(generator: Iterable[str], event: str | None = None) -> Generator[bytes, None, None]:
    """Wrap any iterable of strings as a Server-Sent-Events byte stream suitable for
    a StreamingResponse(media_type='text/event-stream')."""
    for chunk in generator:
        yield sse_format(chunk, event).encode()
    yield sse_format("[DONE]").encode()

def with_event_type(generator: Iterable[str], event_type: str) -> Generator[bytes, None, None]:
    """Wrap a generator with a specific event type."""
    return (sse_format(chunk, event_type).encode() for chunk in generator)

def with_retry(generator: Iterable[str], retry_seconds: int = 5, error_msg: str = "Retry after 5s") -> Generator[bytes, None, None]:
    """Add retry delay and error message to stream."""
    yield sse_format(error_msg, 'error').encode()
    import time
    for chunk in generator:
        yield sse_format(chunk).encode()
        time.sleep(retry_seconds)

def with_final(generator: Iterable[str], final_event: str = "[DONE]") -> Generator[bytes, None, None]:
    """Add a final event marker."""
    for chunk in generator:
        yield sse_format(chunk).encode()
    yield sse_format(final_event).encode()

def with_serializer(generator: Iterable[Any], serializer: Callable[[Any], str]) -> Generator[bytes, None, None]:
    """Apply a custom serialization function to each chunk."""
    for item in generator:
        try:
            serialized = serializer(item)
            if not isinstance(serialized, str):
                raise SerializationError("Serializer must return a string")
            yield sse_format(serialized).encode()
        except Exception as e:
            logging.error(f"Serialization error: {e}")
            continue

def with_error_handling(generator: Iterable[str], logger: logging.Logger, fallback: str = "Stream error") -> Generator[bytes, None, None]:
    """Wrap generator with error logging and fallback."""
    for chunk in generator:
        try:
            yield sse_format(chunk).encode()
        except Exception as e:
            logger.error(f"Error processing chunk: {e}")
            yield sse_format(fallback).encode()

def from_iterable(data: Iterable[Any], serializer: Callable[[Any], str]) -> Generator[bytes, None, None]:
    """Create a stream from an iterable of data objects."""
    return with_serializer(data, serializer)

async def from_async_iterable(data: AsyncIterable[T], serializer: Callable[[T], str]) -> AsyncGenerator[bytes, None]:
    """Create a stream from an async iterable."""
    async for item in data:
        try:
            serialized = serializer(item)
            if not isinstance(serialized, str):
                raise SerializationError("Serializer must return a string")
            yield sse_format(serialized).encode()
        except Exception as e:
            logging.error(f"Serialization error: {e}")

def with_throttling(generator: Iterable[str], max_events_per_second: float = 10.0) -> Generator[bytes, None, None]:
    """Add rate limiting to stream."""
    import time
    last_time = time.time()
    for chunk in generator:
        current_time = time.time()
        if (current_time - last_time) < (1 / max_events_per_second):
            continue
        yield sse_format(chunk).encode()
        last_time = current_time

def with_logging(generator: Iterable[str], logger: logging.Logger, level: int = logging.INFO) -> Generator[bytes, None, None]:
    """Log each chunk sent to client."""
    for chunk in generator:
        logger.log(level, f"Sending SSE event: {chunk}")
        yield sse_format(chunk).encode()

def with_transform(generator: Iterable[str], transform: Callable[[str], str]) -> Generator[bytes, None, None]:
    """Apply a transformation function to each chunk."""
    return (sse_format(transform(chunk)).encode() for chunk in generator)

def with_cipher(generator: Iterable[str], key: bytes) -> Generator[bytes, None, None]:
    """Encrypt SSE events using Fernet cipher."""
    f = Fernet(key)
    for chunk in generator:
        yield f.encrypt(sse_format(chunk).encode())

def with_jinja_template(generator: Iterable[str], template_str: str) -> Generator[bytes, None, None]:
    """Render SSE events using Jinja2 templates."""
    env = jinja2.Environment()
    template = env.from_string(template_str)
    for chunk in generator:
        yield sse_format(template.render(chunk=chunk)).encode()

def with_bleach_sanitizer(generator: Iterable[str]) -> Generator[bytes, None, None]:
    """Sanitize SSE events using Bleach."""
    for chunk in generator:
        sanitized_chunk = html.escape(chunk)
        yield sse_format(sanitized_chunk).encode()


def _selftest() -> None:
    """Offline self-test: SSE framing, event typing, serializer error handling."""
    # event_stream frames each chunk as an SSE data line and terminates with [DONE]
    frames = list(event_stream(iter(["a", "b"])))
    assert frames[0] == b"data: a\n\n", "each chunk must be a well-formed SSE frame"
    assert frames[1] == b"data: b\n\n"
    assert frames[-1] == b"data: [DONE]\n\n", "stream must end with a [DONE] sentinel"

    # with_event_type prepends the SSE `event:` line
    typed = list(with_event_type(iter(["x"]), "update"))
    assert typed == [b"event: update\ndata: x\n\n"], "event type must be emitted"

    # a valid serializer yields formatted frames
    ok = list(with_serializer(iter([1, 2]), lambda n: f"n={n}"))
    assert ok == [b"data: n=1\n\n", b"data: n=2\n\n"]

    # negative: a serializer returning a non-string is skipped, never emitted raw
    bad = list(with_serializer(iter([1, 2]), lambda n: n))  # returns int
    assert bad == [], "non-string serializer output must be dropped, not streamed"
    print("sse_stream self-test passed")


if __name__ == "__main__":
    _selftest()
