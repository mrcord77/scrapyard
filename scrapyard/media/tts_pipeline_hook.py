"""
tts_pipeline_hook — ** The `scrapyard.media.tts_pipeline_hook` module provides a reusable interface for integrating Text-to-Speech (TTS) pipelines into media processing workflows. It enables flexible hooking of TTS servi

### PART-META-JSON
{
  "name": "tts_pipeline_hook",
  "layer": "media",
  "purpose": "Provides a reusable interface for integrating Text-to-Speech (TTS) pipelines into media processing workflows. It enables flexible hooking of TTS servi.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: register_hook(name, hook, default); get_hook(name); synthesize_speech(text, voice, format, hook, hook_name); TTSHook(...).",
  "outputs": "Returns: register_hook -> None; get_hook -> TTSHook; synthesize_speech -> bytes.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.media.tts_pipeline_hook`.",
  "example": "from scrapyard.media.tts_pipeline_hook import *",
  "import_path": "scrapyard.media.tts_pipeline_hook"
}
### END-PART-META
"""

import logging
import os
import sqlite3
import tempfile
from typing import Any, Dict, Optional, Protocol, runtime_checkable

# SQLAlchemy 2.x imports for future persistence compatibility

logger = logging.getLogger(__name__)

# Hook registry storage
_registered_hooks: Dict[str, Any] = {}
_default_hook_name: Optional[str] = None


@runtime_checkable
class TTSHook(Protocol):
    """Protocol defining the interface for TTS pipeline hooks."""
    
    def synthesize_speech(self, text: str, voice: str, format: str) -> bytes:
        """Synthesize speech from text.
        
        Args:
            text: The text to synthesize
            voice: The voice identifier to use
            format: The output audio format (e.g., 'wav', 'mp3')
            
        Returns:
            Audio data as bytes
        """
        ...


def register_hook(name: str, hook: TTSHook, default: bool = False) -> None:
    """Register a TTS hook implementation.
    
    Args:
        name: Unique identifier for this hook
        hook: The hook implementation conforming to TTSHook protocol
        default: Whether to set this as the default hook
    """
    _registered_hooks[name] = hook
    global _default_hook_name
    if default or _default_hook_name is None:
        _default_hook_name = name
    logger.debug(f"Registered TTS hook: {name}")


def get_hook(name: Optional[str] = None) -> TTSHook:
    """Retrieve a registered hook.
    
    Args:
        name: Name of the hook to retrieve. If None, returns the default hook.
        
    Returns:
        The requested hook implementation.
        
    Raises:
        KeyError: If the requested hook is not found.
        RuntimeError: If no default hook is set and no name is provided.
    """
    if name is None:
        if _default_hook_name is None:
            raise RuntimeError("No default TTS hook registered")
        name = _default_hook_name
    
    if name not in _registered_hooks:
        raise KeyError(f"TTS hook '{name}' not registered")
    
    return _registered_hooks[name]


def synthesize_speech(
    text: str, 
    voice: str, 
    format: str, 
    hook: Optional[TTSHook] = None,
    hook_name: Optional[str] = None
) -> bytes:
    """Synthesize speech using the specified TTS hook.
    
    Args:
        text: The text to synthesize into speech
        voice: The voice identifier to use for synthesis
        format: The output audio format
        hook: Optional direct hook instance to use (bypasses registry)
        hook_name: Optional name of registered hook to use
        
    Returns:
        Audio data as bytes.
        
    Raises:
        RuntimeError: If no hook is provided or registered.
    """
    if hook is not None:
        return hook.synthesize_speech(text, voice, format)
    
    h = get_hook(hook_name)
    return h.synthesize_speech(text, voice, format)


def _selftest() -> bool:
    """Execute self-contained unit tests.
    
    Returns:
        True if all tests pass.
        
    Raises:
        AssertionError: If any test fails.
    """
    # Test 1: Verify TTSHook interface is correctly defined and usable
    assert hasattr(TTSHook, 'synthesize_speech')
    assert callable(getattr(TTSHook, 'synthesize_speech', None))
    
    # Create a mock implementation for testing
    class MockTTSBackend:
        def synthesize_speech(self, text: str, voice: str, format: str) -> bytes:
            # Deterministic mock output for testing
            payload = f"[MOCK_AUDIO:text={text},voice={voice},format={format}]"
            return payload.encode('utf-8')
    
    # Verify mock conforms to protocol
    mock_instance = MockTTSBackend()
    assert isinstance(mock_instance, TTSHook)
    
    # Test 2: Test synthesize_speech() with mock data (direct hook)
    result = synthesize_speech("Hello world", "test_voice", "wav", hook=mock_instance)
    expected = b"[MOCK_AUDIO:text=Hello world,voice=test_voice,format=wav]"
    assert result == expected, f"Expected {expected}, got {result}"
    
    # Test 3: Test hook registration and default usage
    register_hook("mock_tts", mock_instance, default=True)
    
    # Test via hook_name parameter
    result2 = synthesize_speech("Test message", "alice", "mp3", hook_name="mock_tts")
    expected2 = b"[MOCK_AUDIO:text=Test message,voice=alice,format=mp3]"
    assert result2 == expected2
    
    # Test via default hook (no hook or hook_name specified)
    result3 = synthesize_speech("Default test", "bob", "ogg")
    expected3 = b"[MOCK_AUDIO:text=Default test,voice=bob,format=ogg]"
    assert result3 == expected3
    
    # Test 4: Verify error handling for invalid hook requests
    try:
        get_hook("nonexistent_hook")
        assert False, "Should have raised KeyError for nonexistent hook"
    except KeyError:
        pass  # Expected
    
    # Test 5: Self-contained test with temporary SQLite
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "tts_test.db")
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE synthesis_log (
                    id INTEGER PRIMARY KEY,
                    text TEXT NOT NULL,
                    voice TEXT NOT NULL,
                    format TEXT NOT NULL,
                    result_size INTEGER
                )
            """)
            
            # Log synthesis operations
            cursor.execute(
                "INSERT INTO synthesis_log (text, voice, format, result_size) VALUES (?, ?, ?, ?)",
                ("Hello world", "test_voice", "wav", len(result))
            )
            conn.commit()
            
            # Verify data integrity
            cursor.execute("SELECT text, voice, format, result_size FROM synthesis_log")
            row = cursor.fetchone()
            assert row == ("Hello world", "test_voice", "wav", len(result))
            
        finally:
            conn.close()
    
    logger.info("_selftest PASSED")
    return True


if __name__ == "__main__":
    _selftest()
