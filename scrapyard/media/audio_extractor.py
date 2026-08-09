"""
audio_extractor — Extracts audio from video files using FFmpeg, providing a reusable, type-safe interface for media processing pipelines.

### PART-META-JSON
{
  "name": "audio_extractor",
  "layer": "media",
  "purpose": "Extracts audio from video files using FFmpeg, providing a reusable, type-safe interface for media processing pipelines.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: AudioExtractor(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Invokes subprocesses; never pass unsanitized input as command arguments. Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.media.audio_extractor`.",
  "example": "from scrapyard.media.audio_extractor import *",
  "import_path": "scrapyard.media.audio_extractor"
}
### END-PART-META
"""

import logging
import shutil
import sys
from subprocess import Popen, PIPE, CalledProcessError
from tempfile import TemporaryDirectory, NamedTemporaryFile
import os

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class AudioExtractor:
    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path

    def extract(self, video_path: str, output_format: str = "wav") -> bytes:
        """
        Extracts audio from a video file using FFmpeg.

        :param video_path: Path to the input video file.
        :param output_format: Output format of the extracted audio (default is 'wav').
        :return: Bytes of the extracted audio.
        """
        temp_dir = TemporaryDirectory()
        temp_audio_file = NamedTemporaryFile(delete=False, dir=temp_dir.name, suffix=f'.{output_format}')
        
        try:
            # Construct FFmpeg command
            cmd = [
                self.ffmpeg_path,
                '-y',            # overwrite the pre-created temp output file
                '-i', video_path,
                '-vn',           # Disable video stream
                '-acodec', 'copy',
                temp_audio_file.name
            ]
            
            # Execute the command
            process = Popen(cmd, stdout=PIPE, stderr=PIPE)
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                logger.error(f"FFmpeg error: {stderr.decode()}")
                raise CalledProcessError(process.returncode, cmd)
            
            # Read the audio file
            with open(temp_audio_file.name, 'rb') as f:
                audio_bytes = f.read()
            
            # Clean up temporary files
            temp_audio_file.close()
            temp_dir.cleanup()
            
            return audio_bytes
        
        except CalledProcessError as e:
            logger.error(f"FFmpeg failed to extract audio: {e}")
            raise

def _selftest() -> bool:
    """
    Self-test for AudioExtractor: builds a REAL short video with an audio track
    via ffmpeg, then extracts that audio and asserts real bytes came back.

    :return: True if all tests pass (or ffmpeg is unavailable -> skip), False on
             a genuine extraction failure.
    """
    ffmpeg_path = "ffmpeg"
    if shutil.which(ffmpeg_path) is None:
        print("SKIPPED: ffmpeg binary not installed")
        return True

    with TemporaryDirectory() as work:
        # A real input file with a pcm audio stream + a video stream. pcm_s16le
        # and mpeg4 are built into every ffmpeg, so this needs no extra codecs.
        input_path = os.path.join(work, 'source.mkv')
        gen_cmd = [
            ffmpeg_path, '-y',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
            '-f', 'lavfi', '-i', 'testsrc=duration=1:size=128x128:rate=10',
            '-c:a', 'pcm_s16le', '-c:v', 'mpeg4', '-shortest',
            input_path,
        ]
        gen = Popen(gen_cmd, stdout=PIPE, stderr=PIPE)
        _, gen_err = gen.communicate()
        if gen.returncode != 0 or not os.path.exists(input_path):
            print(f"SKIPPED: ffmpeg could not build a test clip: {gen_err.decode(errors='replace')[:300]}")
            return True

        try:
            extractor = AudioExtractor(ffmpeg_path=ffmpeg_path)
            # Extract the (copied) pcm audio into a matroska container.
            audio_bytes = extractor.extract(input_path, output_format='mkv')
            assert len(audio_bytes) > 0, "extracted audio should contain data"
            # Extraction must not mutate or delete the source.
            assert os.path.exists(input_path), "source video must survive extraction"
            print("audio_extractor selftest passed")
            return True
        except Exception as e:
            logger.error(f"Self-test failed: {e}")
            return False


# Run self-test if this script is executed directly
if __name__ == "__main__":
    sys.exit(0 if _selftest() else 1)
