"""
media_metadata_prober — ** The `scrapyard.media.media_metadata_prober` module provides a reusable, extensible system for probing and extracting metadata from media files, supporting images, videos, and audio. It abstracts me

### PART-META-JSON
{
  "name": "media_metadata_prober",
  "layer": "media",
  "purpose": "Provides a reusable, extensible system for probing and extracting metadata from media files, supporting images, videos, and audio. It abstracts me.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: probe_media_metadata(file_path, timeout); MediaMetadataProber(...).",
  "outputs": "Returns: probe_media_metadata -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.media.media_metadata_prober`.",
  "example": "from scrapyard.media.media_metadata_prober import *",
  "import_path": "scrapyard.media.media_metadata_prober"
}
### END-PART-META
"""
import os
import logging
import tempfile
from typing import Dict, Any

# Import necessary modules for media processing and metadata extraction
try:
    import ffmpeg  # Assuming it's installed in the environment
except ImportError:
    ffmpeg = None

logger = logging.getLogger(__name__)

class MediaMetadataProber:
    def __init__(self):
        self._metadata = {}

    def probe(self, file_path: str) -> Dict[str, Any]:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")

        if ffmpeg is None:
            raise RuntimeError(
                "ffmpeg-python is not installed; cannot probe media metadata "
                "(pip install ffmpeg-python, plus the ffmpeg binary on PATH)")

        # Extract metadata using ffmpeg
        try:
            probe_result = ffmpeg.probe(file_path)
            self._metadata.update(probe_result)

            return self._metadata
        except Exception as e:
            logger.error(f"Failed to extract metadata from {file_path}: {e}")
            raise

    def get_metadata(self) -> Dict[str, Any]:
        return self._metadata


def probe_media_metadata(file_path: str, timeout: float = 10.0) -> Dict[str, Any]:
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File does not exist: {file_path}")

    # Use MediaMetadataProber to extract metadata
    prober = MediaMetadataProber()
    return prober.probe(file_path)


def _selftest():
    """Offline selftest: verifies the dep-free path (missing-file rejection,
    fresh metadata state) with real assertions, then skips the ffmpeg probe leg
    cleanly when the optional dependency is absent."""
    # --- dep-free logic, always runs (real negative case) ---
    prober = MediaMetadataProber()
    assert prober.get_metadata() == {}, "fresh prober must have empty metadata"

    missing = os.path.join(tempfile.gettempdir(), "scrapyard_no_such_media_xyz.jpg")
    raised = False
    try:
        probe_media_metadata(missing)
    except FileNotFoundError:
        raised = True
    assert raised, "probing a missing file must raise FileNotFoundError"

    # --- ffmpeg leg: skip cleanly when the optional dep is absent ---
    if ffmpeg is None:
        print("media_metadata_prober selftest: SKIPPED (ffmpeg-python not "
              "installed); path validation verified")
        return

    # ffmpeg-python present: a truncated/invalid media file must raise (real
    # error path), never silently 'succeed'. Holds whether or not the ffmpeg
    # binary itself is on PATH (missing binary also raises).
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        bad_path = os.path.join(temp_dir, "bad.jpg")
        with open(bad_path, "wb") as f:
            f.write(b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x00")
        bad_raised = False
        try:
            probe_media_metadata(bad_path)
        except Exception:
            bad_raised = True
        assert bad_raised, "probing an invalid media file must raise"
    print("media_metadata_prober selftest: PASS (ffmpeg-python present; "
          "error path verified)")


if __name__ == "__main__":
    _selftest()
