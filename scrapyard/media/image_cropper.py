"""
image_cropper — Flexible image cropping using absolute pixel coordinates or aspect
ratios (with center/top-left/bottom-right anchoring), built on Pillow.

### PART-META-JSON
{
  "name": "image_cropper",
  "layer": "media",
  "purpose": "Crops PIL images two ways: crop_image/crop_by_coords take absolute pixel rectangles with full bounds validation, and crop_by_ratio extracts the largest region matching a 'W:H' aspect ratio anchored center, top_left, or bottom_right - composing with image_resizer and image_converter for media pipelines.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "Pillow"
  ],
  "inputs": "PIL.Image objects, crop rectangles (x, y, width, height), aspect-ratio strings like '16:9', anchor names.",
  "outputs": "New cropped PIL.Image objects (inputs are never mutated).",
  "files_created": [],
  "security_notes": "Pure in-memory Pillow operations: no network, subprocess, file, or secret handling. Decoding untrusted images upstream is the real risk surface (Pillow decompression bombs) - this module only receives already-decoded Image objects and validates all crop rectangles against image bounds, raising ValueError instead of silently clamping, so hostile coordinates cannot yield out-of-range reads or misleading results.",
  "ai_usage": "crop_image(img, x, y, w, h) for absolute crops; ImageCropper(img).crop_by_ratio('16:9', 'center') for aspect crops.",
  "example": "from scrapyard.media.image_cropper import crop_image, ImageCropper",
  "import_path": "scrapyard.media.image_cropper"
}
### END-PART-META
"""

from PIL import Image
import logging

logger = logging.getLogger(__name__)

_VALID_ANCHORS = ("center", "top_left", "bottom_right")


def crop_image(image: Image.Image, x: int, y: int, width: int, height: int) -> Image.Image:
    """
    Crop an image using absolute pixel coordinates.

    :param image: The PIL Image object to be cropped.
    :param x: X-coordinate of the top-left corner of the crop rectangle.
    :param y: Y-coordinate of the top-left corner of the crop rectangle.
    :param width: Width of the crop rectangle (> 0).
    :param height: Height of the crop rectangle (> 0).
    :return: A new cropped PIL Image object.
    :raises ValueError: If the rectangle is empty or falls outside the image.
    """
    if not isinstance(image, Image.Image):
        raise ValueError("image must be a PIL.Image.Image")
    if width <= 0 or height <= 0:
        raise ValueError(f"crop size must be positive, got {width}x{height}")
    img_w, img_h = image.size
    if x < 0 or y < 0 or x + width > img_w or y + height > img_h:
        raise ValueError(
            f"crop rectangle ({x},{y},{x + width},{y + height}) exceeds "
            f"image bounds {img_w}x{img_h}")
    return image.crop((x, y, x + width, y + height))


class ImageCropper:
    """Stateful cropper bound to one source image."""

    def __init__(self, image: Image.Image):
        if not isinstance(image, Image.Image):
            raise ValueError("image must be a PIL.Image.Image")
        self.image = image
        self.width, self.height = image.size

    def crop_by_coords(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """Crop using absolute pixel coordinates (validated against bounds)."""
        return crop_image(self.image, x, y, width, height)

    def crop_by_ratio(self, ratio: str, anchor: str = "center") -> Image.Image:
        """
        Crop the largest region of the image matching an aspect ratio.

        :param ratio: Aspect ratio as 'width:height' (e.g. '16:9').
        :param anchor: Where to take the crop from when trimming the excess:
            'center', 'top_left', or 'bottom_right'.
        :return: A new cropped PIL Image with the requested aspect ratio.
        """
        try:
            ratio_w, ratio_h = (int(part) for part in ratio.split(":"))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"ratio must look like '16:9', got {ratio!r}") from exc
        if ratio_w <= 0 or ratio_h <= 0:
            raise ValueError(f"ratio terms must be positive, got {ratio!r}")
        if anchor not in _VALID_ANCHORS:
            raise ValueError(f"anchor must be one of {_VALID_ANCHORS}, got {anchor!r}")

        target = ratio_w / ratio_h
        current = self.width / self.height

        if current > target:
            # Image too wide: full height, trim width.
            crop_h = self.height
            crop_w = max(1, round(self.height * target))
        else:
            # Image too tall (or exact): full width, trim height.
            crop_w = self.width
            crop_h = max(1, round(self.width / target))

        excess_x = self.width - crop_w
        excess_y = self.height - crop_h
        if anchor == "center":
            x, y = excess_x // 2, excess_y // 2
        elif anchor == "top_left":
            x, y = 0, 0
        else:  # bottom_right
            x, y = excess_x, excess_y

        return crop_image(self.image, x, y, crop_w, crop_h)


def _selftest():
    """Offline selftest with in-memory images; failures raise (never swallowed)."""
    img = Image.new("RGB", (1024, 768), color="red")

    # Absolute crop
    cropped = crop_image(img, 50, 50, 300, 200)
    assert cropped.size == (300, 200), cropped.size

    # Bounds validation is real, not clamped
    for bad in [(-1, 0, 10, 10), (0, 0, 2000, 10), (1000, 700, 100, 100),
                (0, 0, 0, 10)]:
        try:
            crop_image(img, *bad)
            raise AssertionError(f"should reject {bad}")
        except ValueError:
            pass

    cropper = ImageCropper(img)

    # 16:9 of a 4:3 image keeps full width: 1024 x 576
    wide = cropper.crop_by_ratio("16:9", "center")
    assert wide.size == (1024, 576), wide.size

    # 1:1 keeps full height: 768 x 768
    square = cropper.crop_by_ratio("1:1")
    assert square.size == (768, 768), square.size

    # 9:16 (portrait target on landscape image) keeps full height, trims width
    tall = cropper.crop_by_ratio("9:16", "top_left")
    assert tall.size == (432, 768), tall.size

    # Anchor placement: paint a marker in the top-left, verify anchors differ
    marked = Image.new("RGB", (100, 50), "black")
    for px in range(10):
        marked.putpixel((px, 0), (255, 255, 255))
    mc = ImageCropper(marked)
    tl = mc.crop_by_ratio("1:1", "top_left")     # x=0..50
    br = mc.crop_by_ratio("1:1", "bottom_right")  # x=50..100
    assert tl.size == br.size == (50, 50)
    assert tl.getpixel((0, 0)) == (255, 255, 255)
    assert br.getpixel((0, 0)) == (0, 0, 0)

    # crop_by_coords delegates with validation
    assert cropper.crop_by_coords(0, 0, 10, 10).size == (10, 10)

    # Invalid ratio/anchor inputs
    for bad_ratio in ["16x9", "0:9", "a:b", ""]:
        try:
            cropper.crop_by_ratio(bad_ratio)
            raise AssertionError(f"should reject ratio {bad_ratio!r}")
        except ValueError:
            pass
    try:
        cropper.crop_by_ratio("16:9", "middle")
        raise AssertionError("should reject unknown anchor")
    except ValueError:
        pass

    print("image_cropper selftest: all tests passed")


if __name__ == "__main__":
    _selftest()
