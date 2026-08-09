"""
image_converter — Converts images between formats (PNG/JPEG/BMP/GIF/WEBP/TIFF) with mode
handling (RGBA->RGB flattening for JPEG), optional resizing, and batch conversion.

### PART-META-JSON
{
  "name": "image_converter",
  "layer": "media",
  "purpose": "Converts images between formats using Pillow, with color-mode normalization (e.g. RGBA/P to RGB for JPEG), optional proportional resizing, quality control, and file/in-memory APIs plus batch directory conversion.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "Pillow"
  ],
  "inputs": "PIL.Image objects, image file paths, or bytes; target format name; optional max dimensions and JPEG/WEBP quality.",
  "outputs": "Converted PIL.Image objects, bytes, or files written to caller-specified paths; batch conversion returns a per-file result list.",
  "files_created": [
    "Output image files only at caller-specified paths (convert_file/convert_directory)."
  ],
  "security_notes": "Decoding attacker-supplied images is a real attack surface (decompression bombs, malformed headers). Pillow's MAX_IMAGE_PIXELS bomb guard is left at its default and is honored here; do not raise it for untrusted input. Output paths are taken verbatim from the caller - callers must validate/normalize paths before passing user-controlled names to convert_file/convert_directory to avoid path traversal. No network access; no secrets handled.",
  "ai_usage": "Use convert_image(img, 'JPEG') for in-memory work, convert_file(src, dst) for files, convert_directory(src_dir, dst_dir, 'PNG') for batches.",
  "example": "from scrapyard.media.image_converter import convert_file; convert_file('in.png', 'out.jpg', quality=90)",
  "import_path": "scrapyard.media.image_converter"
}
### END-PART-META
"""

from __future__ import annotations

import io
import os
from typing import Dict, List, Optional, Tuple, Union

from PIL import Image

# Formats that cannot store an alpha channel; images get flattened onto a
# background color before saving to these.
_NO_ALPHA_FORMATS = {"JPEG", "BMP"}

# Canonical format-name aliases (file-extension style -> Pillow format name).
_FORMAT_ALIASES = {
    "JPG": "JPEG",
    "TIF": "TIFF",
}

SUPPORTED_FORMATS = {"PNG", "JPEG", "BMP", "GIF", "WEBP", "TIFF"}


def normalize_format(fmt: str) -> str:
    """Normalize a user-supplied format name ('jpg', '.png', 'JPEG') to a Pillow format."""
    if not fmt or not isinstance(fmt, str):
        raise ValueError("format must be a non-empty string")
    f = fmt.strip().lstrip(".").upper()
    f = _FORMAT_ALIASES.get(f, f)
    if f not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format {fmt!r}; supported: {sorted(SUPPORTED_FORMATS)}")
    return f


def _prepare_mode(image: Image.Image, target_format: str,
                  background: Tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """Return an image whose color mode is storable in target_format.

    RGBA/LA/P-with-transparency images are flattened onto `background` for
    formats without alpha support; palette images are expanded otherwise.
    """
    if target_format in _NO_ALPHA_FORMATS:
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            base = Image.new("RGB", rgba.size, background)
            base.paste(rgba, mask=rgba.getchannel("A"))
            return base
        if image.mode not in ("RGB", "L", "CMYK"):
            return image.convert("RGB")
        return image
    # Alpha-capable target: just expand palettes so edits behave predictably.
    if image.mode == "P":
        return image.convert("RGBA" if "transparency" in image.info else "RGB")
    return image


def _fit_within(image: Image.Image, max_width: Optional[int],
                max_height: Optional[int]) -> Image.Image:
    """Proportionally shrink image to fit within the given bounds (no upscaling)."""
    if not max_width and not max_height:
        return image
    w, h = image.size
    mw = max_width or w
    mh = max_height or h
    if mw <= 0 or mh <= 0:
        raise ValueError("max dimensions must be positive")
    scale = min(mw / w, mh / h, 1.0)
    if scale >= 1.0:
        return image
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return image.resize(new_size, resample=Image.LANCZOS)


def convert_image(image: Image.Image, target_format: str, *,
                  max_width: Optional[int] = None,
                  max_height: Optional[int] = None,
                  background: Tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """Convert a PIL image's mode (and optionally size) for the target format.

    Returns a new PIL.Image ready to be saved as `target_format`.
    """
    if not isinstance(image, Image.Image):
        raise ValueError("image must be a PIL.Image.Image")
    fmt = normalize_format(target_format)
    out = _prepare_mode(image, fmt, background)
    out = _fit_within(out, max_width, max_height)
    return out


def convert_bytes(data: bytes, target_format: str, *,
                  quality: int = 85,
                  max_width: Optional[int] = None,
                  max_height: Optional[int] = None) -> bytes:
    """Convert encoded image bytes to another format; returns encoded bytes."""
    fmt = normalize_format(target_format)
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        out = convert_image(img, fmt, max_width=max_width, max_height=max_height)
        buf = io.BytesIO()
        save_kwargs: Dict[str, object] = {}
        if fmt in ("JPEG", "WEBP"):
            save_kwargs["quality"] = int(quality)
        out.save(buf, format=fmt, **save_kwargs)
        return buf.getvalue()


def convert_file(src_path: Union[str, os.PathLike], dst_path: Union[str, os.PathLike], *,
                 target_format: Optional[str] = None,
                 quality: int = 85,
                 max_width: Optional[int] = None,
                 max_height: Optional[int] = None) -> str:
    """Convert an image file to another format.

    If target_format is omitted it is inferred from dst_path's extension.
    Returns the destination path.
    """
    src_path = os.fspath(src_path)
    dst_path = os.fspath(dst_path)
    if target_format is None:
        ext = os.path.splitext(dst_path)[1]
        if not ext:
            raise ValueError("target_format not given and dst_path has no extension")
        target_format = ext
    fmt = normalize_format(target_format)
    with Image.open(src_path) as img:
        img.load()
        out = convert_image(img, fmt, max_width=max_width, max_height=max_height)
        save_kwargs: Dict[str, object] = {}
        if fmt in ("JPEG", "WEBP"):
            save_kwargs["quality"] = int(quality)
        out.save(dst_path, format=fmt, **save_kwargs)
    return dst_path


def convert_directory(src_dir: Union[str, os.PathLike], dst_dir: Union[str, os.PathLike],
                      target_format: str, *, quality: int = 85,
                      max_width: Optional[int] = None,
                      max_height: Optional[int] = None) -> List[Dict[str, str]]:
    """Convert every readable image directly inside src_dir into dst_dir.

    Returns a list of {'source', 'destination'|'error', 'status'} dicts;
    unreadable/non-image files are reported, not raised.
    """
    src_dir = os.fspath(src_dir)
    dst_dir = os.fspath(dst_dir)
    fmt = normalize_format(target_format)
    os.makedirs(dst_dir, exist_ok=True)
    ext = "." + ("jpg" if fmt == "JPEG" else fmt.lower())
    results: List[Dict[str, str]] = []
    for name in sorted(os.listdir(src_dir)):
        src = os.path.join(src_dir, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(dst_dir, os.path.splitext(name)[0] + ext)
        try:
            convert_file(src, dst, target_format=fmt, quality=quality,
                         max_width=max_width, max_height=max_height)
            results.append({"source": src, "destination": dst, "status": "converted"})
        except Exception as exc:  # report per-file failures, keep batch going
            results.append({"source": src, "error": str(exc), "status": "failed"})
    return results


class ImageConverter:
    """Reusable converter with fixed target format/options."""

    def __init__(self, target_format: str, *, quality: int = 85,
                 max_width: Optional[int] = None, max_height: Optional[int] = None):
        self.target_format = normalize_format(target_format)
        self.quality = quality
        self.max_width = max_width
        self.max_height = max_height

    def convert(self, image: Image.Image) -> Image.Image:
        return convert_image(image, self.target_format,
                             max_width=self.max_width, max_height=self.max_height)

    def convert_file(self, src_path: str, dst_path: str) -> str:
        return convert_file(src_path, dst_path, target_format=self.target_format,
                            quality=self.quality, max_width=self.max_width,
                            max_height=self.max_height)


def _selftest() -> None:
    import tempfile

    # 1. Format normalization
    assert normalize_format("jpg") == "JPEG"
    assert normalize_format(".png") == "PNG"
    try:
        normalize_format("exr")
        raise AssertionError("should reject unsupported format")
    except ValueError:
        pass

    # 2. RGBA -> JPEG flattening (in-memory)
    rgba = Image.new("RGBA", (60, 40), (255, 0, 0, 128))
    out = convert_image(rgba, "JPEG")
    assert out.mode == "RGB", out.mode

    # 3. Bytes round-trip PNG -> JPEG -> open
    buf = io.BytesIO()
    rgba.save(buf, format="PNG")
    jpeg_bytes = convert_bytes(buf.getvalue(), "jpeg", quality=90)
    with Image.open(io.BytesIO(jpeg_bytes)) as reopened:
        assert reopened.format == "JPEG"
        assert reopened.size == (60, 40)

    # 4. Resize-to-fit keeps aspect ratio, never upscales
    big = Image.new("RGB", (400, 200), "blue")
    small = convert_image(big, "PNG", max_width=100, max_height=100)
    assert small.size == (100, 50), small.size
    same = convert_image(big, "PNG", max_width=1000, max_height=1000)
    assert same.size == (400, 200)

    # 5. File + directory conversion
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        src_dir = os.path.join(tmp, "src")
        dst_dir = os.path.join(tmp, "dst")
        os.makedirs(src_dir)
        for i in range(3):
            Image.new("RGBA", (20, 20), (0, 255, 0, 255)).save(
                os.path.join(src_dir, f"im{i}.png"))
        # a non-image file must be reported, not crash the batch
        with open(os.path.join(src_dir, "notes.txt"), "w") as fh:
            fh.write("not an image")
        results = convert_directory(src_dir, dst_dir, "jpg")
        converted = [r for r in results if r["status"] == "converted"]
        failed = [r for r in results if r["status"] == "failed"]
        assert len(converted) == 3 and len(failed) == 1, results
        for r in converted:
            with Image.open(r["destination"]) as img:
                assert img.format == "JPEG"

        # 6. Class API
        conv = ImageConverter("png", max_width=10)
        p = conv.convert_file(os.path.join(src_dir, "im0.png"),
                              os.path.join(tmp, "tiny.png"))
        with Image.open(p) as img:
            assert img.size == (10, 10)

    print("image_converter selftest: all tests passed")


if __name__ == "__main__":
    _selftest()
