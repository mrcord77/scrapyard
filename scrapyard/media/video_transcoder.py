"""
video_transcoder — Transcodes video files to a specified format and resolution using FFmpeg. Provides a reusable, flexible, and robust interface for video processing tasks.

### PART-META-JSON
{
  "name": "video_transcoder",
  "layer": "media",
  "purpose": "Transcodes video files to a specified format and resolution using FFmpeg. Provides a reusable, flexible, and robust interface for video processing tasks.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: transcode_video(input_path, output_path, format, resolution, ffmpeg_options); VideoTranscoder(...).",
  "outputs": "Returns: transcode_video -> None.",
  "files_created": [],
  "security_notes": "Invokes subprocesses; never pass unsanitized input as command arguments. Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.media.video_transcoder`.",
  "example": "from scrapyard.media.video_transcoder import *",
  "import_path": "scrapyard.media.video_transcoder"
}
### END-PART-META
"""

import os
import re
import shutil
import sys
import logging
from subprocess import run, CalledProcessError
from tempfile import TemporaryDirectory
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class VideoTranscoder:
    def __init__(self, input_path: str, output_path: str, ffmpeg_options: Optional[Dict[str, Any]] = None):
        self.input_path = input_path
        self.output_path = output_path
        self.format: Optional[str] = None
        self.resolution: Optional[str] = None
        self.ffmpeg_options = ffmpeg_options or {}

    def set_format(self, format: str) -> None:
        if format in ["mp4", "avi", "mkv"]:
            self.format = format
        else:
            raise ValueError(f"Unsupported format: {format}")

    def set_resolution(self, resolution: str) -> None:
        match = re.match(r'^(\d+)x(\d+)$', resolution)
        if match:
            self.resolution = resolution
        else:
            raise ValueError(f"Invalid resolution format: {resolution}")

    def transcode(self) -> None:
        if not os.path.exists(self.input_path):
            raise FileNotFoundError(f"Input file does not exist: {self.input_path}")

        command = ["ffmpeg", "-y", "-i", self.input_path]
        
        if self.resolution:
            command.extend(["-vf", f"scale={self.resolution}"])
        
        if self.format == "mp4":
            command.extend(["-c:v", "libx264"])
        elif self.format == "avi":
            command.extend(["-c:v", "mpeg4"])
        elif self.format == "mkv":
            command.extend(["-c:v", "libx264"])
        
        # Add custom FFmpeg options
        for key, value in self.ffmpeg_options.items():
            if key.startswith('-'):
                command.extend([key, str(value)])
            else:
                command.extend([f"-{key}", str(value)])
        
        command.extend(["-c:a", "copy"])
        command.append(self.output_path)

        try:
            result = run(command, check=True, capture_output=True, text=True)
            logger.info(f"Transcoding successful: {self.input_path} -> {self.output_path}")
        except CalledProcessError as e:
            logger.error(f"FFmpeg transcoding failed: {e.stderr}")
            raise RuntimeError(f"FFmpeg transcoding failed: {e.stderr}") from e


def transcode_video(input_path: str, output_path: str, format: str, resolution: str, ffmpeg_options: Optional[Dict[str, Any]] = None) -> None:
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    if format not in ["mp4", "avi", "mkv"]:
        raise ValueError(f"Unsupported format: {format}")

    if not re.match(r'^\d+x\d+$', resolution):
        raise ValueError(f"Invalid resolution format: {resolution}")

    transcoder = VideoTranscoder(input_path, output_path, ffmpeg_options)
    transcoder.set_format(format)
    transcoder.set_resolution(resolution)
    transcoder.transcode()


def _selftest() -> bool:
    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        input_file = os.path.join(temp_dir, "sample_input.mp4")
        output_file = os.path.join(temp_dir, "output_transcoded.mp4")

        # --- Real, ffmpeg-independent validation (always runs before any skip) ---
        # Missing input raises FileNotFoundError
        try:
            transcode_video(os.path.join(temp_dir, "nonexistent.mp4"), output_file, "mp4", "1920x1080")
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            logger.info("Correctly raised FileNotFoundError for missing input")

        # Class-based invalid format validation
        try:
            VideoTranscoder(input_file, output_file).set_format("xyz")
            assert False, "Should have raised ValueError for invalid format"
        except ValueError:
            logger.info("Correctly raised ValueError for invalid format")

        # Class-based invalid resolution validation
        try:
            VideoTranscoder(input_file, output_file).set_resolution("1080p")
            assert False, "Should have raised ValueError for invalid resolution"
        except ValueError:
            logger.info("Correctly raised ValueError for invalid resolution")

        # transcode_video()-level format/resolution validation happens after the
        # existence check, so give it a real (dummy) input file to get past that.
        with open(input_file, "wb") as fh:
            fh.write(b"\x00" * 64)
        try:
            transcode_video(input_file, output_file, "xyz", "1920x1080")
            assert False, "Should have raised ValueError for unsupported format"
        except ValueError:
            logger.info("Correctly raised ValueError for unsupported format")
        try:
            transcode_video(input_file, output_file, "mp4", "1080p")
            assert False, "Should have raised ValueError for invalid resolution format"
        except ValueError:
            logger.info("Correctly raised ValueError for invalid resolution format")

        # --- ffmpeg gate: skip the live transcoding legs when the binary is absent ---
        if shutil.which("ffmpeg") is None:
            print("SKIPPED: ffmpeg binary not installed")
            return True

        # Remove the dummy file; the live legs need a real ffmpeg-built source.
        os.remove(input_file)

        # Create a valid sample video using FFmpeg test source
        try:
            create_cmd = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=1280x720:rate=1",
                "-pix_fmt", "yuv420p", input_file
            ]
            run(create_cmd, check=True, capture_output=True, text=True)
            logger.info(f"Created test video: {input_file}")
        except CalledProcessError as e:
            logger.error(f"Failed to create test video: {e.stderr}")
            print("SKIPPED: ffmpeg present but cannot synthesize a test clip")
            return True

        # Test 1: Successful transcoding to MP4 at 1080p
        transcode_video(input_file, output_file, "mp4", "1920x1080")
        assert os.path.exists(output_file), "Output file does not exist"
        assert os.path.getsize(output_file) > 0, "Transcoded file is empty"
        # Check file is reasonable size for a video (>1KB)
        assert os.path.getsize(output_file) > 1000, "Transcoded file too small to be valid video"
        
        # Test 2: Custom FFmpeg options
        output_custom = os.path.join(temp_dir, "output_custom.mp4")
        transcode_video(input_file, output_custom, "mp4", "1920x1080", {"-crf": "23", "-preset": "fast"})
        assert os.path.exists(output_custom), "Output file with custom options does not exist"
        
        # Test 3: Invalid input file raises FileNotFoundError
        try:
            transcode_video(os.path.join(temp_dir, "nonexistent.mp4"), output_file, "mp4", "1920x1080")
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            logger.info("Correctly raised FileNotFoundError for missing input")
        
        # Test 4: FFmpeg command failure handling (invalid input format)
        bad_input = os.path.join(temp_dir, "bad.txt")
        with open(bad_input, 'w') as f:
            f.write("This is not a video file")
        
        try:
            transcode_video(bad_input, output_file, "mp4", "1920x1080")
            assert False, "Should have raised RuntimeError for FFmpeg failure"
        except (RuntimeError, CalledProcessError):
            logger.info("Correctly handled FFmpeg command failure")
        
        # Test 5: Invalid format validation in transcode_video
        try:
            transcode_video(input_file, output_file, "xyz", "1920x1080")
            assert False, "Should have raised ValueError for unsupported format"
        except ValueError:
            logger.info("Correctly raised ValueError for unsupported format")
        
        # Test 6: Invalid resolution validation
        try:
            transcode_video(input_file, output_file, "mp4", "1080p")
            assert False, "Should have raised ValueError for invalid resolution format"
        except ValueError:
            logger.info("Correctly raised ValueError for invalid resolution format")
        
        # Test 7: Class-based API with resolution format validation
        transcoder = VideoTranscoder(input_file, os.path.join(temp_dir, "class_output.mp4"))
        transcoder.set_format("mp4")
        transcoder.set_resolution("1920x1080")
        transcoder.transcode()
        assert os.path.exists(transcoder.output_path), "Class-based transcoding failed"

        logger.info("All self-tests passed")
        print("video_transcoder selftest: PASS (live ffmpeg transcode verified)")
        return True


if __name__ == "__main__":
    sys.exit(0 if _selftest() else 1)
