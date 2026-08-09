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
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        test_image_path = os.path.join(temp_dir, "test.jpg")
        with open(test_image_path, "wb") as f:
            f.write(b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x00")

        try:
            metadata = probe_media_metadata(test_image_path)
            assert "format" in metadata
            assert "streams" in metadata
            logger.info(f"Self-test passed: {metadata}")
        except Exception as e:
            logger.error(f"Self-test failed: {e}")


if __name__ == "__main__":
    _selftest()
