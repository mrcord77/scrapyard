"""
image_watermarker — ** The `scrapyard.media.image_watermarker` module provides a reusable, flexible image watermarking utility, integrating with common media processing workflows. It enables adding watermarks to images w

### PART-META-JSON
{
  "name": "image_watermarker",
  "layer": "media",
  "purpose": "Provides a reusable, flexible image watermarking utility, integrating with common media processing workflows. It enables adding watermarks to images w.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: add_watermark(image, watermark); Watermark(...).",
  "outputs": "Returns: add_watermark -> Image.Image.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.media.image_watermarker`.",
  "example": "from scrapyard.media.image_watermarker import *",
  "import_path": "scrapyard.media.image_watermarker"
}
### END-PART-META
"""
from typing import Tuple
import os
import logging
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

class Watermark:
    def __init__(self, text: str, font_size: int, opacity: float, position: Tuple[int, int]) -> None:
        self.text = text
        self.font_size = font_size
        self.opacity = opacity
        self.position = position

def add_watermark(image: Image.Image, watermark: Watermark) -> Image.Image:
    """
    Add a text watermark to an image with configurable opacity and position.
    
    Args:
        image: PIL Image object (any mode)
        watermark: Watermark configuration object
        
    Returns:
        PIL Image with watermark applied (mode preserved when possible)
    """
    if not watermark.text:
        return image.copy()
    
    original_mode = image.mode
    # Convert to RGBA to support alpha blending
    if original_mode != 'RGBA':
        rgba_image = image.convert('RGBA')
    else:
        rgba_image = image.copy()
    
    # Create transparent overlay for the watermark
    overlay = Image.new('RGBA', rgba_image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Load font with specified size, fallback to default
    font = ImageFont.load_default()
    if watermark.font_size > 0:
        try:
            # Try common system fonts
            font = ImageFont.truetype("DejaVuSans.ttf", watermark.font_size)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("arial.ttf", watermark.font_size)
            except (OSError, IOError):
                try:
                    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", watermark.font_size)
                except (OSError, IOError):
                    logger.debug("Could not load specified font size, using default")
    
    # Calculate text dimensions
    if hasattr(font, 'getbbox'):
        bbox = font.getbbox(watermark.text)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    else:
        # Fallback for older Pillow versions
        text_width, text_height = draw.textsize(watermark.text, font=font)
    
    # Position is treated as center point of the text
    x, y = watermark.position
    x = x - text_width // 2
    y = y - text_height // 2
    
    # Apply opacity clamped to [0, 1]
    alpha = int(255 * max(0.0, min(1.0, watermark.opacity)))
    # Use black text for visibility on light backgrounds
    fill = (0, 0, 0, alpha)
    
    draw.text((x, y), watermark.text, font=font, fill=fill)
    
    # Composite overlay onto original
    result = Image.alpha_composite(rgba_image, overlay)
    
    # Restore original mode if possible
    if original_mode != 'RGBA':
        try:
            result = result.convert(original_mode)
        except ValueError:
            pass  # Keep RGBA if conversion fails
    
    return result

def _selftest() -> None:
    """Offline self-test with temporary SQLite for validation."""
    import sqlite3
    import time
    from tempfile import TemporaryDirectory
    
    start_time = time.time()
    
    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        # Validate SQLite integration as per spec
        db_path = os.path.join(temp_dir, "validation.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE validation (id INTEGER PRIMARY KEY, module TEXT, timestamp REAL)")
        cursor.execute("INSERT INTO validation (module, timestamp) VALUES (?, ?)", 
                      ("scrapyard.media.image_watermarker", time.time()))
        conn.commit()
        cursor.execute("SELECT module FROM validation WHERE id=1")
        row = cursor.fetchone()
        assert row is not None and row[0] == "scrapyard.media.image_watermarker", "SQLite validation failed"
        conn.close()
        
        # Test Watermark object creation with valid parameters
        watermark = Watermark(text="SAMPLE", font_size=24, opacity=0.5, position=(100, 100))
        assert watermark.text == "SAMPLE"
        assert watermark.font_size == 24
        assert watermark.opacity == 0.5
        assert watermark.position == (100, 100)
        
        # Create sample image (white background)
        image = Image.new("RGB", (200, 200), "white")
        
        # Apply watermark
        watermarked_image = add_watermark(image, watermark)
        assert isinstance(watermarked_image, Image.Image)
        assert watermarked_image.size == (200, 200)
        
        # Verify opacity and position: pixels at center should be gray (blended), not white or pure black
        pixels = watermarked_image.load()
        center_pixel = pixels[100, 100]
        r, g, b = center_pixel
        
        # With black text at 0.5 opacity on white background, expect ~127-128
        assert 50 < r < 200, f"Opacity not respected: red={r}"
        assert 50 < g < 200, f"Opacity not respected: green={g}"
        assert 50 < b < 200, f"Opacity not respected: blue={b}"
        
        # Verify corners remain white (position respected - watermark is centered, not at corners)
        assert pixels[0, 0] == (255, 255, 255), "Watermark position incorrect - affected corner"
        assert pixels[199, 199] == (255, 255, 255), "Watermark position incorrect - affected corner"
        
        # Save and verify output
        output_path = os.path.join(temp_dir, "watermarked_sample.png")
        watermarked_image.save(output_path)
        assert os.path.exists(output_path), "Watermarked image not saved correctly"
        
        # Verify execution time
        elapsed = time.time() - start_time
        assert elapsed < 20, f"Self-test exceeded time limit: {elapsed:.1f}s"
        
        logger.info(f"Self-test completed successfully in {elapsed:.2f}s")

if __name__ == "__main__":
    _selftest()
