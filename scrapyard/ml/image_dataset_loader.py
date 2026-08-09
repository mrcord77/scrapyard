"""
image_dataset_loader — ** The `scrapyard.ml.image_dataset_loader` module provides a reusable, flexible interface for loading image datasets from common formats, enabling seamless integration into ML pipelines. It abstracts 

### PART-META-JSON
{
  "name": "image_dataset_loader",
  "layer": "ml",
  "purpose": "Provides a reusable, flexible interface for loading image datasets from common formats, enabling seamless integration into ML pipelines. It abstracts.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: load_image(path, resize); ImageLoader(...).",
  "outputs": "Returns: load_image -> np.ndarray.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.ml.image_dataset_loader`.",
  "example": "from scrapyard.ml.image_dataset_loader import *",
  "import_path": "scrapyard.ml.image_dataset_loader"
}
### END-PART-META
"""
import logging
import os
import sqlite3
import tempfile
from typing import Optional, List, Tuple, Iterator

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

PART_META_JSON = '{"name": "scrapyard.ml.image_dataset_loader", "layer": "ml"}'


def load_image(path: str, resize: Optional[Tuple[int, int]] = None) -> np.ndarray:
    """Load an image from disk and optionally resize it.
    
    Args:
        path: Path to the image file.
        resize: Optional (width, height) tuple to resize to.
        
    Returns:
        Numpy array of shape (H, W, 3) with dtype uint8.
        
    Raises:
        FileNotFoundError: If the image file does not exist.
        ValueError: If the image cannot be loaded or decoded.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image not found: {path}")
    
    try:
        with Image.open(path) as img:
            # Convert to RGB to ensure consistent 3-channel output
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            if resize is not None:
                img = img.resize(resize, Image.Resampling.LANCZOS)
            
            return np.array(img)
    except Exception as e:
        raise ValueError(f"Failed to load image {path}: {e}") from e


class ImageLoader:
    """Loader for discovering and batch-loading images from a directory."""
    
    def __init__(self, root: str, formats: Optional[List[str]] = None):
        """Initialize the image loader.
        
        Args:
            root: Root directory to recursively search for images.
            formats: List of supported extensions (without dot). 
                    Defaults to ["jpg", "png"] if not specified.
        """
        self.root = root
        if formats is None:
            formats = ["jpg", "png"]
        # Normalize: lowercase and strip dots
        self.formats = [f.lower().lstrip('.') for f in formats]
    
    def list_images(self) -> List[str]:
        """List all image paths in the root directory matching specified formats.
        
        Returns:
            Sorted list of full file paths.
            
        Raises:
            ValueError: If root directory does not exist.
        """
        if not os.path.isdir(self.root):
            raise ValueError(f"Root directory does not exist: {self.root}")
        
        images = []
        for dirpath, _, filenames in os.walk(self.root):
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower().lstrip('.')
                if ext in self.formats:
                    images.append(os.path.join(dirpath, filename))
        
        images.sort()
        return images
    
    def load_all(self, batch_size: int = 32) -> Iterator[np.ndarray]:
        """Load all discovered images in batches.
        
        Args:
            batch_size: Number of images per batch. Must be positive.
            
        Yields:
            Batches of images as numpy arrays of shape (N, H, W, 3).
            
        Raises:
            ValueError: If batch_size is not positive.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        
        image_paths = self.list_images()
        current_batch: List[np.ndarray] = []
        
        for path in image_paths:
            try:
                img_array = load_image(path)
                current_batch.append(img_array)
                
                if len(current_batch) >= batch_size:
                    yield np.stack(current_batch)
                    current_batch = []
            except Exception as e:
                logger.warning(f"Skipping {path}: {e}")
                continue
        
        if current_batch:
            yield np.stack(current_batch)


def _selftest():
    """Offline self-test suite."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Create test images (same size for batching compatibility)
        img1_path = os.path.join(tmpdir, "test1.jpg")
        img2_path = os.path.join(tmpdir, "test2.png")
        img3_path = os.path.join(tmpdir, "subdir", "test3.jpg")
        bad_path = os.path.join(tmpdir, "bad.txt")
        
        os.makedirs(os.path.dirname(img3_path), exist_ok=True)
        
        # Create valid images
        Image.new('RGB', (64, 64), color='red').save(img1_path, 'JPEG')
        Image.new('RGB', (64, 64), color='blue').save(img2_path, 'PNG')
        Image.new('RGB', (64, 64), color='green').save(img3_path, 'JPEG')
        
        # Create invalid image file
        with open(bad_path, 'w') as f:
            f.write("not an image")
        
        # Test load_image basic functionality
        arr1 = load_image(img1_path)
        assert isinstance(arr1, np.ndarray)
        assert arr1.shape == (64, 64, 3)
        assert arr1.dtype == np.uint8
        # Check red color (RGB: 255, 0, 0) - allow for JPEG compression artifacts
        assert arr1[32, 32, 0] > 250  # Red channel high
        assert arr1[32, 32, 1] < 10   # Green channel low
        assert arr1[32, 32, 2] < 10   # Blue channel low
        
        # Test load_image with resize
        arr_resized = load_image(img1_path, resize=(32, 32))
        assert arr_resized.shape == (32, 32, 3)
        
        # Test load_image FileNotFoundError
        try:
            load_image(os.path.join(tmpdir, "nonexistent.jpg"))
            assert False, "Expected FileNotFoundError"
        except FileNotFoundError:
            pass
        
        # Test load_image ValueError for invalid image
        try:
            load_image(bad_path)
            assert False, "Expected ValueError"
        except ValueError:
            pass
        
        # Test ImageLoader initialization defaults
        loader = ImageLoader(tmpdir)
        assert loader.formats == ["jpg", "png"]
        
        # Test list_images
        images = loader.list_images()
        assert len(images) == 3
        assert sorted(images) == sorted([img1_path, img2_path, img3_path])
        
        # Test format filtering
        loader_png = ImageLoader(tmpdir, formats=["png"])
        png_images = loader_png.list_images()
        assert len(png_images) == 1
        assert png_images[0] == img2_path
        
        # Test invalid root
        try:
            bad_loader = ImageLoader(os.path.join(tmpdir, "nonexistent"))
            bad_loader.list_images()
            assert False, "Expected ValueError"
        except ValueError:
            pass
        
        # Test load_all batching
        batches = list(loader.load_all(batch_size=2))
        assert len(batches) == 2  # 2 + 1
        assert batches[0].shape == (2, 64, 64, 3)
        assert batches[1].shape == (1, 64, 64, 3)
        
        # Test load_all invalid batch_size
        try:
            list(loader.load_all(batch_size=0))
            assert False, "Expected ValueError"
        except ValueError:
            pass
        
        # Test SQLite connection handling (verify proper close)
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        conn.close()
        
        logger.info("_selftest passed successfully")


if __name__ == "__main__":
    _selftest()
