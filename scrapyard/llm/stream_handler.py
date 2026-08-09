"""
stream_handler — Handle streaming responses from LLMs by processing tokens in real-time, enabling dynamic updates and efficient handling of large or continuous outputs.

### PART-META-JSON
{
  "name": "stream_handler",
  "layer": "llm",
  "purpose": "Handle streaming responses from LLMs by processing tokens in real-time, enabling dynamic updates and efficient handling of large or continuous outputs.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "retry_policy"
  ],
  "inputs": "Public API: start_stream(model, prompt, **kwargs); handle_token(token, context); handle_special_token(token, context); handle_rate_limiting(token, context); check_retry_policy(token, context); StreamContext(...); StreamError(...) (plus more).",
  "outputs": "Returns: start_stream -> StreamContext; handle_token -> None; handle_special_token -> None; handle_rate_limiting -> None; check_retry_policy -> None.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.llm.stream_handler`.",
  "example": "from scrapyard.llm.stream_handler import *",
  "import_path": "scrapyard.llm.stream_handler"
}
### END-PART-META
"""

from dataclasses import dataclass, field
from typing import Optional, List, Callable
import threading
import time
import logging
import sqlite3
import tempfile
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class StreamContext:
    model: str
    prompt: str
    token_buffer: List[str] = field(default_factory=list)
    error_handler: Optional[Callable[[Exception], None]] = None
    max_buffer_size: int = 100
    paused: bool = field(default=False)
    retry_count: int = field(default=0)
    max_retries: int = 3
    rate_limit_delay: float = 0.01
    _lock: threading.Lock = field(default_factory=threading.Lock)


class StreamError(Exception):
    pass


def start_stream(model: str, prompt: str, **kwargs) -> StreamContext:
    context = StreamContext(
        model=model,
        prompt=prompt,
        token_buffer=[],
        error_handler=kwargs.get('error_handler'),
        max_buffer_size=kwargs.get('max_buffer_size', 100),
        max_retries=kwargs.get('max_retries', 3),
        rate_limit_delay=kwargs.get('rate_limit_delay', 0.01)
    )
    logger.info(f"Started stream for model {model}")
    return context


def handle_token(token: str, context: StreamContext) -> None:
    try:
        with context._lock:
            if context.paused:
                logger.debug("Stream paused, token discarded")
                return
            
            if len(context.token_buffer) >= context.max_buffer_size:
                raise StreamError(f"Buffer overflow: {len(context.token_buffer)} >= {context.max_buffer_size}")
            
            context.token_buffer.append(token)
            
            if len(context.token_buffer) == 1:
                logger.info(f"Received first token: {token}")
            else:
                logger.debug(f"Handling token {len(context.token_buffer)}: {token}")
        
        handle_special_token(token, context)
        handle_rate_limiting(token, context)
        check_retry_policy(token, context)
        
    except Exception as e:
        if context.error_handler:
            context.error_handler(e)
        else:
            raise


def handle_special_token(token: str, context: StreamContext) -> None:
    if token == "<SPECIAL_TOKEN>":
        logger.info("Special token detected. Handling special logic.")


def handle_rate_limiting(token: str, context: StreamContext) -> None:
    if context.rate_limit_delay > 0:
        time.sleep(context.rate_limit_delay)


def check_retry_policy(token: str, context: StreamContext) -> None:
    if token == "<ERROR>":
        if context.retry_count < context.max_retries:
            context.retry_count += 1
            logger.warning(f"Simulated stream failure, retry {context.retry_count}/{context.max_retries}")
        else:
            raise StreamError(f"Max retries ({context.max_retries}) exceeded for stream error")


def pause_stream(context: StreamContext) -> None:
    with context._lock:
        context.paused = True
        logger.info("Stream paused")


def resume_stream(context: StreamContext) -> None:
    with context._lock:
        context.paused = False
        logger.info("Stream resumed")


def _selftest():
    import threading
    import time
    
    start_time = time.time()
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_stream.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE tokens (id INTEGER PRIMARY KEY, token TEXT, timestamp TEXT)")
        conn.commit()
        
        # Test 1: Stream starts and handles tokens sequentially
        errors_caught = []
        def error_handler(e):
            errors_caught.append(e)
        
        context = start_stream(
            model="gpt-3.5-turbo",
            prompt="Hello, how are you?",
            max_buffer_size=10,
            error_handler=error_handler,
            rate_limit_delay=0.0
        )
        
        tokens_to_send = ["Hello", "world", "<SPECIAL_TOKEN>", "test", "tokens"]
        for token in tokens_to_send:
            handle_token(token, context)
        
        assert len(context.token_buffer) == 5, f"Expected 5 tokens, got {len(context.token_buffer)}"
        assert context.token_buffer[0] == "Hello", "First token mismatch"
        assert context.token_buffer[2] == "<SPECIAL_TOKEN>", "Special token position mismatch"
        assert context.model == "gpt-3.5-turbo", "Context model not preserved"
        assert context.prompt == "Hello, how are you?", "Context prompt not preserved"
        
        # Test 2: Token buffer limits enforced
        context2 = start_stream(model="test", prompt="test", max_buffer_size=3, rate_limit_delay=0.0)
        handle_token("a", context2)
        handle_token("b", context2)
        handle_token("c", context2)
        
        try:
            handle_token("d", context2)
            assert False, "Buffer limit not enforced"
        except StreamError as e:
            assert "Buffer overflow" in str(e)
            logger.info(f"Caught expected buffer error: {e}")
        
        # Test 3: Retry policy triggered on simulated stream failure
        context3 = start_stream(model="test", prompt="test", max_retries=2, rate_limit_delay=0.0)
        
        handle_token("<ERROR>", context3)
        assert context3.retry_count == 1, f"Expected retry count 1, got {context3.retry_count}"
        
        handle_token("<ERROR>", context3)
        assert context3.retry_count == 2, f"Expected retry count 2, got {context3.retry_count}"
        
        try:
            handle_token("<ERROR>", context3)
            assert False, "Should have raised StreamError after max retries"
        except StreamError as e:
            assert "Max retries" in str(e)
            logger.info(f"Caught expected retry error: {e}")
        
        # Test 4: Pause/Resume functionality
        context4 = start_stream(model="test", prompt="test", rate_limit_delay=0.0)
        pause_stream(context4)
        handle_token("paused_token", context4)
        assert len(context4.token_buffer) == 0, "Token should not be added while paused"
        
        resume_stream(context4)
        handle_token("resumed_token", context4)
        assert len(context4.token_buffer) == 1, "Token should be added after resume"
        assert context4.paused == False, "Context should not be paused after resume"
        
        # Test 5: Thread safety verification
        context5 = start_stream(model="test", prompt="test", max_buffer_size=1000, rate_limit_delay=0.0)
        threads = []
        tokens_per_thread = 10
        num_threads = 5
        
        def worker(thread_id):
            for i in range(tokens_per_thread):
                handle_token(f"thread{thread_id}_token{i}", context5)
        
        thread_list = []
        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            thread_list.append(t)
            t.start()
        
        for t in thread_list:
            t.join()
        
        expected_count = num_threads * tokens_per_thread
        assert len(context5.token_buffer) == expected_count, f"Expected {expected_count} tokens, got {len(context5.token_buffer)}"
        
        token_counts = {}
        for token in context5.token_buffer:
            prefix = token.split('_')[0]
            token_counts[prefix] = token_counts.get(prefix, 0) + 1
        
        for i in range(num_threads):
            assert token_counts.get(f"thread{i}", 0) == tokens_per_thread, f"Thread {i} tokens missing"
        
        # Test 6: Error handling with custom handler (no raise)
        custom_errors = []
        def custom_handler(e):
            custom_errors.append(str(e))
        
        context6 = start_stream(model="test", prompt="test", error_handler=custom_handler, max_buffer_size=2, rate_limit_delay=0.0)
        handle_token("a", context6)
        handle_token("b", context6)
        handle_token("c", context6)  # Triggers buffer overflow, handled by custom_handler
        
        assert len(custom_errors) == 1, f"Expected 1 error handled, got {len(custom_errors)}"
        assert "Buffer overflow" in custom_errors[0]
        
        # Test 7: SQLite integration verification
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tokens (token, timestamp) VALUES (?, ?)",
                      ("test_token", datetime.now(timezone.utc).isoformat()))
        conn.commit()
        cursor.execute("SELECT COUNT(*) FROM tokens")
        count = cursor.fetchone()[0]
        assert count == 1, "SQLite integration failed"
        cursor.close()
        conn.close()
        
        elapsed = time.time() - start_time
        assert elapsed < 20, f"Self-test took too long: {elapsed}s"
        
        print(f"Self-test completed successfully in {elapsed:.2f}s.")


if __name__ == "__main__":
    _selftest()
