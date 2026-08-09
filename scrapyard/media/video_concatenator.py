"""
video_concatenator — Concatenates video files losslessly with ffmpeg's concat demuxer
(stream copy), with an optional re-encode mode for mismatched codecs.

### PART-META-JSON
{
  "name": "video_concatenator",
  "layer": "media",
  "purpose": "Concatenates multiple video files into one output using ffmpeg's concat demuxer via subprocess (stream copy by default, optional re-encode), gated on ffmpeg being present on PATH with honest errors when it is not.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "ffmpeg (external binary, optional at import time)"
  ],
  "inputs": "List of existing video file paths sharing codec/parameters (for copy mode); output path; optional reencode flag and extra ffmpeg args.",
  "outputs": "The concatenated video file at output_path; returns the output path.",
  "files_created": [
    "A temporary ffmpeg concat list file (removed after the run).",
    "The output video at the caller-specified path."
  ],
  "security_notes": "Invokes the ffmpeg binary via subprocess with a list argv (never shell=True), so no shell injection through filenames. Input paths are written into an ffmpeg concat list file with quote escaping and 'safe' mode disabled to allow absolute Windows paths - do not pass untrusted arbitrary strings as paths, since ffmpeg concat lists can reference any readable file. ffmpeg itself parses untrusted media; keep it patched. No network access; no secrets handled.",
  "ai_usage": "Check ffmpeg_available() first; call concatenate_videos([a, b, c], 'out.mp4'). Use reencode=True when inputs have mismatched codecs/resolutions.",
  "example": "from scrapyard.media.video_concatenator import concatenate_videos; concatenate_videos(['a.mp4','b.mp4'], 'joined.mp4')",
  "import_path": "scrapyard.media.video_concatenator"
}
### END-PART-META
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import List, Optional, Sequence, Union

PathLike = Union[str, os.PathLike]


class FfmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg is required but not present on PATH."""


def ffmpeg_available() -> bool:
    """True if an ffmpeg binary is on PATH."""
    return shutil.which("ffmpeg") is not None


def _require_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise FfmpegNotFoundError(
            "ffmpeg binary not found on PATH. Install ffmpeg (https://ffmpeg.org) "
            "and ensure it is on PATH; video concatenation cannot run without it."
        )
    return exe


def build_concat_list(paths: Sequence[PathLike]) -> str:
    """Build the text content of an ffmpeg concat-demuxer list file.

    Single quotes in paths are escaped per ffmpeg's concat list syntax.
    """
    lines = []
    for p in paths:
        p = os.path.abspath(os.fspath(p))
        escaped = p.replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


def concatenate_videos(input_paths: Sequence[PathLike], output_path: PathLike, *,
                       reencode: bool = False,
                       extra_args: Optional[List[str]] = None,
                       overwrite: bool = True,
                       timeout: Optional[float] = None) -> str:
    """Concatenate input videos into output_path using ffmpeg's concat demuxer.

    Copy mode (default) requires inputs to share codec/parameters and is
    lossless; reencode=True re-encodes (libx264/aac) to tolerate mismatches.
    Raises FfmpegNotFoundError when ffmpeg is absent, FileNotFoundError for
    missing inputs, and RuntimeError with ffmpeg's stderr tail on failure.
    """
    if not input_paths:
        raise ValueError("input_paths must contain at least one video")
    inputs = [os.path.abspath(os.fspath(p)) for p in input_paths]
    for p in inputs:
        if not os.path.isfile(p):
            raise FileNotFoundError(f"input video not found: {p}")
    output_path = os.path.abspath(os.fspath(output_path))
    exe = _require_ffmpeg()

    list_fd, list_path = tempfile.mkstemp(suffix=".txt", prefix="concat_")
    try:
        with os.fdopen(list_fd, "w", encoding="utf-8") as fh:
            fh.write(build_concat_list(inputs))

        cmd = [exe, "-hide_banner", "-loglevel", "error",
               "-y" if overwrite else "-n",
               "-f", "concat", "-safe", "0", "-i", list_path]
        if reencode:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac"]
        else:
            cmd += ["-c", "copy"]
        if extra_args:
            cmd += list(extra_args)
        cmd.append(output_path)

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip()[-2000:]
            raise RuntimeError(
                f"ffmpeg concat failed (exit {proc.returncode}): {tail}")
        return output_path
    finally:
        try:
            os.unlink(list_path)
        except OSError:
            pass


class VideoConcatenator:
    """Collects clips then concatenates them in one call."""

    def __init__(self, reencode: bool = False):
        self.reencode = reencode
        self._clips: List[str] = []

    def add(self, path: PathLike) -> "VideoConcatenator":
        self._clips.append(os.fspath(path))
        return self

    @property
    def clips(self) -> List[str]:
        return list(self._clips)

    def concatenate(self, output_path: PathLike, **kwargs) -> str:
        return concatenate_videos(self._clips, output_path,
                                  reencode=self.reencode, **kwargs)


def _selftest() -> None:
    # Offline-safe checks: list-file construction, validation, honest gating.
    content = build_concat_list([r"C:\vids\a.mp4", r"C:\vids\it's here.mp4"])
    assert "file '" in content and content.endswith("\n")
    assert "'\\''" in content, "single quote must be escaped"

    try:
        concatenate_videos([], "out.mp4")
        raise AssertionError("empty input list must raise")
    except ValueError:
        pass

    conc = VideoConcatenator().add("a.mp4").add("b.mp4")
    assert conc.clips == ["a.mp4", "b.mp4"]

    if not ffmpeg_available():
        # Honest gating: absent ffmpeg must raise FfmpegNotFoundError, and the
        # selftest skips the live run gracefully (still exits 0).
        import tempfile as _tf
        with _tf.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            fake = os.path.join(tmp, "clip.mp4")
            with open(fake, "wb") as fh:
                fh.write(b"\x00" * 16)
            try:
                concatenate_videos([fake], os.path.join(tmp, "out.mp4"))
                raise AssertionError("must raise FfmpegNotFoundError without ffmpeg")
            except FfmpegNotFoundError:
                pass
        print("SKIPPED: ffmpeg binary not installed")
        return

    # Live path: synthesize two tiny clips with ffmpeg, concat, verify output.
    exe = _require_ffmpeg()
    import tempfile as _tf
    with _tf.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        clips = []
        for i in range(2):
            clip = os.path.join(tmp, f"clip{i}.mp4")
            gen = subprocess.run(
                [exe, "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "testsrc=duration=0.5:size=64x64:rate=10",
                 "-pix_fmt", "yuv420p", clip],
                capture_output=True, text=True)
            if gen.returncode != 0:
                # ffmpeg present but cannot synthesize (stripped build) - skip live leg.
                print("video_concatenator selftest: PASS "
                      "(ffmpeg cannot synthesize test clips; live concat skipped)")
                return
            clips.append(clip)
        out = os.path.join(tmp, "joined.mp4")
        result = concatenate_videos(clips, out)
        assert os.path.isfile(result) and os.path.getsize(result) > 0
        sizes = [os.path.getsize(c) for c in clips]
        assert os.path.getsize(result) > max(sizes) * 1.2, \
            "concatenated file should be substantially larger than one clip"
    print("video_concatenator selftest: PASS (live ffmpeg concat verified)")


if __name__ == "__main__":
    _selftest()
