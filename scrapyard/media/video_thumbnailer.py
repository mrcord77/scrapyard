"""
video_thumbnailer — Generates video thumbnails at specified timecodes via real ffmpeg
subprocess invocations (gated on ffmpeg presence, honest errors on failure), with an
explicit placeholder mode for offline tests.

### PART-META-JSON
{
  "name": "video_thumbnailer",
  "layer": "media",
  "purpose": "Captures a single BMP frame from a video at a given timecode using ffmpeg (-ss seek, -vframes 1) invoked via subprocess with list argv. ffmpeg absence or failure raises honest RuntimeError/ThumbnailError; a deterministic 1x1 BMP placeholder is written ONLY when the caller explicitly passes allow_placeholder=True (used by offline selftests), never silently.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "ffmpeg (external binary; gated via shutil.which, optional at import time)"
  ],
  "inputs": "Source video path, timecode in seconds (>= 0), output image path; optional allow_placeholder flag for offline/test use.",
  "outputs": "A BMP thumbnail written to output_path; returns None. Raises ThumbnailError when ffmpeg is missing/fails and placeholders are not allowed.",
  "files_created": [
    "The thumbnail image at the caller-specified output path (parent dirs created)."
  ],
  "security_notes": "Invokes ffmpeg via subprocess with list argv (no shell), so filenames cannot inject shell commands; ffmpeg itself parses untrusted video containers - keep it patched and cap input sizes for hostile uploads. Output paths are caller-supplied with no traversal guard; contain them upstream when user-controlled. allow_placeholder=True fabricates a 1x1 BMP instead of a real frame - never enable it where downstream consumers treat thumbnails as evidence of video content. No network or secret handling.",
  "ai_usage": "generate_thumbnail(video, 1.5, 'thumb.bmp') for one-offs; ThumbnailGenerator(video, t).save(path) to reuse settings. Check ffmpeg presence via shutil.which('ffmpeg') before batch runs.",
  "example": "from scrapyard.media.video_thumbnailer import generate_thumbnail",
  "import_path": "scrapyard.media.video_thumbnailer"
}
### END-PART-META
"""

from __future__ import annotations

import logging
import os
import shutil
import struct
import subprocess
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["ThumbnailGenerator", "ThumbnailError", "generate_thumbnail"]

_FFMPEG_CMD: str = "ffmpeg"


class ThumbnailError(RuntimeError):
    """Raised when a real thumbnail cannot be produced."""


def _is_ffmpeg_available() -> bool:
    """Return True if the ffmpeg executable is on PATH."""
    return shutil.which(_FFMPEG_CMD) is not None


def _write_fallback_image(path: str) -> None:
    """Write a minimal valid 1x1 24-bit BMP file to ``path`` (test placeholder)."""
    width = 1
    height = 1
    row_size = ((24 * width + 31) // 32) * 4
    image_size = row_size * height
    file_size = 14 + 40 + image_size

    header = (
        b"BM"
        + struct.pack("<I", file_size)
        + b"\x00\x00\x00\x00"
        + struct.pack("<I", 54)
    )

    dib_header = struct.pack(
        "<IiiHHIIiiII",
        40,  # header size
        width,
        height,
        1,  # planes
        24,  # bits per pixel
        0,  # compression
        image_size,
        0,  # x ppm
        0,  # y ppm
        0,  # colors used
        0,  # important colors
    )

    # One red pixel in BGR order, padded to a 4-byte row.
    pixel_data = b"\x00\x00\xff" + b"\x00" * (row_size - 3)

    with open(path, "wb") as fh:
        fh.write(header + dib_header + pixel_data)


def _validate_inputs(video_path: Any, timecode: Any, output_path: Any) -> None:
    """Raise appropriate exceptions for invalid caller inputs."""
    if not isinstance(video_path, str):
        raise TypeError("video_path must be a string")
    if not video_path:
        raise ValueError("video_path must not be empty")

    if isinstance(timecode, bool) or not isinstance(timecode, (int, float)):
        raise TypeError("timecode must be a number")
    if timecode < 0:
        raise ValueError("timecode must be non-negative")

    if not isinstance(output_path, str):
        raise TypeError("output_path must be a string")
    if not output_path:
        raise ValueError("output_path must not be empty")


def generate_thumbnail(video_path: str, timecode: float, output_path: str, *,
                       allow_placeholder: bool = False) -> None:
    """Create a thumbnail image from ``video_path`` at ``timecode``.

    Uses ffmpeg to render a real BMP frame. If ffmpeg is missing or fails,
    a ThumbnailError is raised - unless the caller explicitly passes
    allow_placeholder=True (offline/test mode), in which case a minimal
    valid BMP placeholder is written instead.

    Raises:
        TypeError/ValueError: For invalid arguments.
        ThumbnailError: When no real thumbnail can be produced and
            placeholders were not explicitly allowed.
    """
    _validate_inputs(video_path, timecode, output_path)

    output_dir = os.path.dirname(os.path.abspath(output_path))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    if not _is_ffmpeg_available():
        if allow_placeholder:
            logger.warning("ffmpeg unavailable; writing PLACEHOLDER thumbnail "
                           "(allow_placeholder=True)")
            _write_fallback_image(output_path)
            return
        raise ThumbnailError(
            "ffmpeg binary not found on PATH; cannot generate a real thumbnail. "
            "Install ffmpeg (https://ffmpeg.org) or pass allow_placeholder=True "
            "in test environments.")

    command = [
        _FFMPEG_CMD,
        "-y",
        "-loglevel", "error",
        "-ss", str(float(timecode)),
        "-i", video_path,
        "-vframes", "1",
        "-f", "image2",
        "-c:v", "bmp",
        output_path,
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        if allow_placeholder:
            logger.warning("ffmpeg invocation failed (%s); writing PLACEHOLDER", exc)
            _write_fallback_image(output_path)
            return
        raise ThumbnailError(f"ffmpeg invocation failed: {exc}") from exc

    if (result.returncode == 0 and os.path.exists(output_path)
            and os.path.getsize(output_path) > 0):
        return

    stderr_tail = (result.stderr or "").strip()[-500:]
    if allow_placeholder:
        logger.warning("ffmpeg failed (%s); writing PLACEHOLDER thumbnail",
                       stderr_tail or f"exit {result.returncode}")
        _write_fallback_image(output_path)
        return
    raise ThumbnailError(
        f"ffmpeg failed to extract a frame from {video_path!r} at t={timecode} "
        f"(exit {result.returncode}): {stderr_tail}")


class ThumbnailGenerator:
    """Class-based interface for generating video thumbnails."""

    def __init__(self, video_path: str, timecode: float) -> None:
        if not isinstance(video_path, str):
            raise TypeError("video_path must be a string")
        if not video_path:
            raise ValueError("video_path must not be empty")
        if isinstance(timecode, bool) or not isinstance(timecode, (int, float)):
            raise TypeError("timecode must be a number")
        if timecode < 0:
            raise ValueError("timecode must be non-negative")

        self.video_path: str = video_path
        self.timecode: float = float(timecode)

    def save(self, output_path: str, *, allow_placeholder: bool = False) -> None:
        """Render and save the thumbnail to ``output_path``."""
        generate_thumbnail(self.video_path, self.timecode, output_path,
                           allow_placeholder=allow_placeholder)


def _selftest() -> None:
    """Selftest: real ffmpeg leg when available, placeholder leg always offline."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Invalid input checks (no ffmpeg needed)
        out = os.path.join(tmpdir, "x.bmp")
        for args, exc_type in [
            (("", 1.0, out), ValueError),
            (("v.mp4", -1.0, out), ValueError),
            (("v.mp4", 1.0, ""), ValueError),
            ((123, 1.0, out), TypeError),
            (("v.mp4", "bad", out), TypeError),
        ]:
            try:
                generate_thumbnail(*args)
                raise AssertionError(f"should reject {args}")
            except exc_type:
                pass

        # Explicit placeholder mode always produces a valid BMP offline
        fake_video = os.path.join(tmpdir, "fake.mp4")
        with open(fake_video, "wb") as fh:
            fh.write(b"not a real video")
        ph = os.path.join(tmpdir, "placeholder.bmp")
        generate_thumbnail(fake_video, 0.5, ph, allow_placeholder=True)
        with open(ph, "rb") as fh:
            assert fh.read(2) == b"BM"

        if not _is_ffmpeg_available():
            # Honest error without ffmpeg, graceful skip of the live leg
            try:
                generate_thumbnail(fake_video, 0.5,
                                   os.path.join(tmpdir, "real.bmp"))
                raise AssertionError("must raise ThumbnailError without ffmpeg")
            except ThumbnailError:
                pass
            print("video_thumbnailer selftest: PASS (ffmpeg absent; live leg skipped)")
            return

        # Live leg: garbage input must raise honestly (no silent placeholder)
        try:
            generate_thumbnail(fake_video, 0.5, os.path.join(tmpdir, "bad.bmp"))
            raise AssertionError("garbage video must raise ThumbnailError")
        except ThumbnailError:
            pass

        # Live leg: synthesize a real clip and capture a real frame
        clip = os.path.join(tmpdir, "clip.mp4")
        gen = subprocess.run(
            [_FFMPEG_CMD, "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10",
             "-pix_fmt", "yuv420p", clip],
            capture_output=True, text=True)
        if gen.returncode != 0:
            print("video_thumbnailer selftest: PASS "
                  "(ffmpeg cannot synthesize test clip; live leg skipped)")
            return
        real_out = os.path.join(tmpdir, "real.bmp")
        generate_thumbnail(clip, 0.5, real_out)
        assert os.path.getsize(real_out) > 100  # a real 64x64 frame, not 1x1
        with open(real_out, "rb") as fh:
            assert fh.read(2) == b"BM"
        gen2 = ThumbnailGenerator(clip, 0.2)
        out2 = os.path.join(tmpdir, "real2.bmp")
        gen2.save(out2)
        assert os.path.isfile(out2) and os.path.getsize(out2) > 100

    print("video_thumbnailer selftest: PASS (live ffmpeg frame capture verified)")


if __name__ == "__main__":
    _selftest()
