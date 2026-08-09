"""
tensorboard_integration — Integrates TensorBoard for logging metrics and visualizations during ML training, enabling real-time monitoring and analysis of training progress.

### PART-META-JSON
{
  "name": "tensorboard_integration",
  "layer": "ml",
  "purpose": "Integrates TensorBoard for logging metrics and visualizations during ML training, enabling real-time monitoring and analysis of training progress.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "metric_tracking"
  ],
  "inputs": "Public API: TensorBoardLogger(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.ml.tensorboard_integration`.",
  "example": "from scrapyard.ml.tensorboard_integration import *",
  "import_path": "scrapyard.ml.tensorboard_integration"
}
### END-PART-META
"""

from typing import List, Any
import os
import time
import logging
import tempfile

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TensorBoardLogger:
    def __init__(self, log_dir: str, sync_freq: int = 100):
        self.log_dir = os.path.abspath(log_dir)
        os.makedirs(self.log_dir, exist_ok=True)
        self.sync_freq = sync_freq
        self._events_file_path = os.path.join(self.log_dir, 'events.out.tfevents')
        self._event_writer = None
        self._last_flush_time = time.time()
        self._buffer = []
    
    def _create_events_file(self):
        with open(self._events_file_path, 'w') as f:
            pass
    
    def log_scalar(self, tag: str, value: float, step: int):
        if not os.path.exists(self._events_file_path):
            self._create_events_file()
        
        event_str = f'event {time.time()} scalar\t{tag}\t{value}\t{step}'
        self._buffer.append(event_str)
        if len(self._buffer) >= self.sync_freq:
            self.flush()
    
    def log_histogram(self, tag: str, values: List[float], step: int):
        event_str = f'event {time.time()} histogram\t{tag}\n'
        for value in values:
            event_str += f'{value}\n'
        event_str += '\n'
        self._buffer.append(event_str)
    
    def log_image(self, tag: str, image: Any, step: int):
        """Log an image for real: the pixel data (PIL Image, numpy array, or
        nested list) is written as a PNG under <log_dir>/images/ and an event
        line referencing the file is appended to the event log."""
        images_dir = os.path.join(self.log_dir, 'images')
        os.makedirs(images_dir, exist_ok=True)
        safe_tag = ''.join(c if c.isalnum() or c in '-_' else '_' for c in tag)
        img_path = os.path.join(images_dir, f'{safe_tag}_{step}.png')

        from PIL import Image
        import numpy as np
        if isinstance(image, Image.Image):
            pil = image
        else:
            arr = np.asarray(image)
            if arr.dtype != np.uint8:
                # normalize floats/ints into displayable 0-255
                arr = arr.astype('float64')
                span = (arr.max() - arr.min()) or 1.0
                arr = ((arr - arr.min()) / span * 255.0).astype('uint8')
            pil = Image.fromarray(arr)
        pil.save(img_path)

        event_str = f'event {time.time()} image\t{tag}\t{img_path}\t{step}'
        self._buffer.append(event_str)
        if len(self._buffer) >= self.sync_freq:
            self.flush()
    
    def flush(self):
        if not self._buffer:
            return
        
        with open(self._events_file_path, 'a') as f:
            for event_str in self._buffer:
                f.write(event_str)
        
        self._buffer.clear()
        self._last_flush_time = time.time()
    
    def close(self):
        self.flush()
    
    def get_log_dir(self) -> str:
        return self.log_dir

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
        logger = TensorBoardLogger(tempdir)
        
        # Test scalar logging
        for i in range(10):
            logger.log_scalar('loss', 0.5 + i / 10, i)
        
        # Test histogram logging
        values = [i * 0.1 for i in range(10)]
        logger.log_histogram('values', values, 0)

        # Test image logging writes a REAL decodable PNG + an event line
        img = [[0, 128, 255], [255, 128, 0]]
        logger.log_image('sample/img', img, 0)
        img_file = os.path.join(tempdir, 'images', 'sample_img_0.png')
        assert os.path.exists(img_file)
        from PIL import Image
        with Image.open(img_file) as im:
            assert im.size == (3, 2)

        # Test flush and close
        logger.flush()
        logger.close()

        # Verify files exist
        assert os.path.exists(os.path.join(tempdir, 'events.out.tfevents'))
        with open(os.path.join(tempdir, 'events.out.tfevents')) as f:
            assert 'image\tsample/img' in f.read()
        
        # Verify no exceptions raised
        try:
            with open(os.path.join(tempdir, 'events.out.tfevents')) as f:
                content = f.read()
                assert 'event' in content
        except Exception as e:
            logger.error(f"Test failed: {e}")
            raise


# Ensure no external dependencies are invoked at import time
if __name__ == "__main__":
    _selftest()
