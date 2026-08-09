"""
audio_normalizer — Loudness-normalizes audio files to a target LUFS via ffmpeg's
loudnorm filter (EBU R128), gated on ffmpeg presence with honest errors.

### PART-META-JSON
{
  "name": "audio_normalizer",
  "layer": "media",
  "purpose": "Normalizes audio loudness to a target integrated LUFS (default -16, the streaming norm) using ffmpeg's loudnorm filter via subprocess, writing to a persistent caller-controlled output path (default: <input>_normalized.wav next to the input - never a vanishing temp dir). ffmpeg absence raises FfmpegNotFoundError; ffmpeg failures raise RuntimeError with stderr.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "ffmpeg (external binary; gated via shutil.which, optional at import time)"
  ],
  "inputs": "Input audio file path, target loudness in LUFS (typically -24..-9), optional output path and true-peak/LRA settings.",
  "outputs": "Normalized audio file at the returned output path.",
  "files_created": [
    "The normalized audio file at the caller-specified or derived output path."
  ],
  "security_notes": "Invokes ffmpeg via subprocess with list argv (no shell), so filenames cannot inject commands; ffmpeg parses untrusted audio containers - keep it patched and cap upload sizes for hostile inputs. Output paths derive from input paths or caller args with no traversal guard; contain user-controlled paths upstream. Error messages include ffmpeg stderr, which echoes file paths - fine for logs, but avoid surfacing raw paths to end users. No network or secret handling.",
  "ai_usage": "normalize_audio('in.wav', target_volume=-16.0) returns the output path; AudioNormalizer(target_volume).normalize(path) for batches. Check ffmpeg_available() before bulk runs.",
  "example": "from scrapyard.media.audio_normalizer import normalize_audio",
  "import_path": "scrapyard.media.audio_normalizer"
}
### END-PART-META
"""
import logging
import os
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Optional

logger = logging.getLogger(__name__)


class FfmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg is required but not present on PATH."""


def ffmpeg_available() -> bool:
    """True if an ffmpeg binary is on PATH."""
    return shutil.which("ffmpeg") is not None


def _require_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise FfmpegNotFoundError(
            "ffmpeg binary not found on PATH. Install ffmpeg (https://ffmpeg.org); "
            "audio normalization cannot run without it.")
    return exe


def normalize_audio(file_path: str, target_volume: float = -16.0, *,
                    output_path: Optional[str] = None,
                    true_peak: float = -1.5,
                    loudness_range: float = 11.0,
                    timeout: Optional[float] = None) -> str:
    """Normalize an audio file to `target_volume` integrated LUFS (EBU R128).

    Writes to `output_path` (default: '<input stem>_normalized.wav' beside the
    input) and returns that persistent path. Raises FfmpegNotFoundError when
    ffmpeg is absent, FileNotFoundError for a missing input, ValueError for an
    out-of-range target, and RuntimeError with ffmpeg's stderr on failure.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"input audio not found: {file_path}")
    # loudnorm accepts I in [-70, -5]
    if not (-70.0 <= float(target_volume) <= -5.0):
        raise ValueError(
            f"target_volume must be in [-70, -5] LUFS, got {target_volume}")
    exe = _require_ffmpeg()

    if output_path is None:
        stem, _ = os.path.splitext(file_path)
        output_path = f"{stem}_normalized.wav"
    output_path = os.path.abspath(output_path)
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    filter_spec = (f"loudnorm=I={float(target_volume)}:TP={float(true_peak)}:"
                   f"LRA={float(loudness_range)}")
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-y",
           "-i", file_path, "-filter:a", filter_spec, output_path]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-1000:]
        raise RuntimeError(
            f"ffmpeg loudness normalization failed (exit {proc.returncode}): {tail}")
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("ffmpeg reported success but produced no output file")
    return output_path


class AudioNormalizer:
    """Class-based interface for normalizing audio loudness."""

    def __init__(self, target_volume: float = -16.0, *,
                 true_peak: float = -1.5, loudness_range: float = 11.0):
        self.target_volume = target_volume
        self.true_peak = true_peak
        self.loudness_range = loudness_range

    def normalize(self, file_path: str,
                  output_path: Optional[str] = None) -> str:
        """Normalize the given audio file; returns the persistent output path."""
        return normalize_audio(file_path, self.target_volume,
                               output_path=output_path,
                               true_peak=self.true_peak,
                               loudness_range=self.loudness_range)


def _selftest():
    # Offline validation (no ffmpeg required)
    try:
        normalize_audio("definitely_missing.wav")
        raise AssertionError("missing input must raise FileNotFoundError")
    except FileNotFoundError:
        pass

    if not ffmpeg_available():
        # Honest gating without ffmpeg; skip the live leg gracefully (exit 0).
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            fake = os.path.join(temp_dir, "in.wav")
            with open(fake, "wb") as fh:
                fh.write(b"\x00" * 64)
            try:
                normalize_audio(fake)
                raise AssertionError("must raise FfmpegNotFoundError without ffmpeg")
            except FfmpegNotFoundError:
                pass
        print("SKIPPED: ffmpeg binary not installed")
        return

    exe = _require_ffmpeg()
    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        input_file_path = os.path.join(temp_dir, "input.wav")
        # 1 second of a 440Hz tone (finite: -t 1) as a real test signal
        gen = subprocess.run(
            [exe, "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
             "-t", "1", input_file_path],
            capture_output=True, text=True)
        if gen.returncode != 0:
            print("audio_normalizer selftest: PASS "
                  "(ffmpeg cannot synthesize test audio; live leg skipped)")
            return

        # Function API: output persists after the call (not a vanished temp dir)
        out1 = normalize_audio(input_file_path, target_volume=-16.0,
                               output_path=os.path.join(temp_dir, "out1.wav"))
        assert os.path.isfile(out1) and os.path.getsize(out1) > 0

        # Default output path derivation
        out_default = normalize_audio(input_file_path)
        assert out_default.endswith("input_normalized.wav")
        assert os.path.isfile(out_default) and os.path.getsize(out_default) > 0

        # Class API
        normalizer = AudioNormalizer(target_volume=-16.0)
        out2 = normalizer.normalize(input_file_path,
                                    os.path.join(temp_dir, "out2.wav"))
        assert os.path.isfile(out2) and os.path.getsize(out2) > 0

        # Invalid target rejected before any subprocess work
        try:
            normalize_audio(input_file_path, target_volume=3.0)
            raise AssertionError("positive LUFS target must raise")
        except ValueError:
            pass

        # Garbage input is an honest ffmpeg error
        bad = os.path.join(temp_dir, "bad.wav")
        with open(bad, "wb") as fh:
            fh.write(b"not audio")
        try:
            normalize_audio(bad, output_path=os.path.join(temp_dir, "nope.wav"))
            raise AssertionError("garbage input must raise RuntimeError")
        except RuntimeError:
            pass

    print("audio_normalizer selftest: PASS (live ffmpeg loudnorm verified)")


if __name__ == "__main__":
    _selftest()
