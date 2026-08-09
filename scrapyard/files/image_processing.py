"""
image_processing — Resize/convert/strip-EXIF images.

### PART-META-JSON
{
  "name": "image_processing",
  "layer": "files",
  "purpose": "Resize/convert/strip-EXIF images.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "pillow"
  ],
  "inputs": "Public API: validate_image_data(data); dimensions(data); make_thumbnail(data, size); ImageConfig(...); AuditHook(...); MetricsHook(...) (plus more).",
  "outputs": "Returns: validate_image_data -> bool; dimensions -> tuple[int, int] | None; make_thumbnail -> bytes | None.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import `validate_image_data` from `scrapyard.files.image_processing` and call it as shown in `example`; run `py -m scrapyard.files.image_processing` to see its offline selftest.",
  "example": "from scrapyard.files.image_processing import validate_image_data",
  "import_path": "scrapyard.files.image_processing"
}
### END-PART-META
"""
from typing import Any, Dict, List, Optional, Tuple, TypeVar
import io
from PIL import Image
from pydantic import BaseModel

STATUS = "core"

class ImageConfig(BaseModel):
    max_size: int = 1048576  # 1MB
    allowed_formats: List[str] = ["JPEG", "PNG", "GIF"]
    quality: int = 85

class AuditHook:
    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    def __call__(self, event: str, details: Dict[str, Any]) -> None:
        self.events.append({"event": event, "details": dict(details)})

class MetricsHook:
    def __init__(self):
        self.values: Dict[str, List[float]] = {}

    def __call__(self, metric_name: str, value: float) -> None:
        self.values.setdefault(metric_name, []).append(float(value))

class ImageResult(BaseModel):
    data: bytes
    metadata: Dict[str, Any]

class ImageError(Exception):
    pass

def validate_image_data(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)) as im:
            return True
    except Exception:
        raise ImageError("Invalid or unsupported image format")

T = TypeVar('T')

class ImageProcessor:
    def __init__(self, config: Optional[ImageConfig] = None):
        self.config = config or ImageConfig()
        self.audit_events: List[Dict[str, Any]] = []
        self.metrics: Dict[str, List[float]] = {}

    def process_image(
        self,
        data: bytes,
        output_format: str = "PNG",
        size: Tuple[int, int] | None = None,
        strip_exif: bool = False,
        quality: int = 85
    ) -> ImageResult:
        if not validate_image_data(data):
            raise ImageError("Invalid or unsupported image format")
        
        try:
            with Image.open(io.BytesIO(data)) as im:
                if size:
                    im.thumbnail(size)
                if strip_exif:
                    im.info = {k: v for k, v in im.info.items() if not k.startswith('exif')}
                # Encode into a single buffer and read the SAME buffer back. The
                # previous version saved to one throwaway BytesIO and returned
                # getvalue() from a second, empty one -> always emitted b"".
                buf = io.BytesIO()
                im.save(buf, format=output_format, quality=quality)
                result = ImageResult(
                    data=buf.getvalue(),
                    metadata={"width": im.width, "height": im.height, "format": output_format}
                )
                self.audit_hook("image_processed", result.metadata)
                self.metrics_hook("output_bytes", len(result.data))
                return result
        except Exception as e:
            raise ImageError(f"Failed to process image: {str(e)}")

    def bulk_process_images(
        self,
        data_list: List[bytes],
        output_format: str = "PNG",
        size: Tuple[int, int] | None = None,
        strip_exif: bool = False,
        quality: int = 85
    ) -> List[ImageResult]:
        results = []
        for data in data_list:
            try:
                result = self.process_image(data, output_format, size, strip_exif, quality)
                results.append(result)
            except ImageError as e:
                results.append(ImageResult(data=None, metadata={"error": str(e)}))
        return results

    def audit_hook(self, event: str, details: Dict[str, Any]) -> None:
        self.audit_events.append({"event": event, "details": dict(details)})

    def metrics_hook(self, metric_name: str, value: float) -> None:
        self.metrics.setdefault(metric_name, []).append(float(value))


# --- grafted from original part (API stability) ---
def dimensions(data: bytes) -> tuple[int, int] | None:
    """Best-effort image dimensions using Pillow if available, else None.
    Kept dependency-light: returns None rather than failing when Pillow is absent."""
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return None

def make_thumbnail(data: bytes, size=(128, 128)) -> bytes | None:
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.thumbnail(size); out = io.BytesIO(); im.save(out, format=im.format or "PNG")
            return out.getvalue()
    except Exception:
        return None


def _selftest() -> None:
    """Offline self-test: synthesize an in-memory PIL image, run the ops, and assert
    the outputs are valid images with the expected dimensions/format."""
    from PIL import Image

    # Build a 100x50 RGB source image entirely in memory.
    src = Image.new("RGB", (100, 50), color=(10, 20, 30))
    raw = io.BytesIO()
    src.save(raw, format="PNG")
    png_bytes = raw.getvalue()
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "sanity: source is a PNG"

    # dimensions() reads size back exactly.
    assert dimensions(png_bytes) == (100, 50), dimensions(png_bytes)

    # process_image resizes (thumbnail keeps aspect ratio) and returns NON-EMPTY,
    # re-openable output of the requested format. This assertion fails on the old
    # throwaway-buffer bug (data would be b"").
    processor = ImageProcessor()
    result = processor.process_image(png_bytes, output_format="PNG", size=(20, 20))
    assert isinstance(result.data, (bytes, bytearray)) and len(result.data) > 0, "output image data is empty"
    reopened = Image.open(io.BytesIO(result.data))
    assert reopened.format == "PNG"
    assert reopened.width <= 20 and reopened.height <= 20, (reopened.width, reopened.height)
    assert result.metadata["width"] <= 20 and result.metadata["height"] <= 20
    assert processor.audit_events[-1]["event"] == "image_processed"
    assert processor.metrics["output_bytes"][-1] == len(result.data)
    audit = AuditHook(); metrics = MetricsHook()
    audit("processed", {"bytes": len(result.data)}); metrics("bytes", len(result.data))
    assert audit.events[-1]["event"] == "processed"
    assert metrics.values["bytes"][-1] == len(result.data)

    # make_thumbnail produces a smaller valid image.
    thumb = make_thumbnail(png_bytes, (10, 10))
    assert thumb is not None and len(thumb) > 0
    tw, th = Image.open(io.BytesIO(thumb)).size
    assert tw <= 10 and th <= 10, (tw, th)

    # Negative/adversarial: non-image bytes are rejected / handled, not silently
    # accepted as a valid image.
    try:
        validate_image_data(b"this is definitely not an image")
        raise AssertionError("garbage bytes were accepted as a valid image")
    except ImageError:
        pass
    assert dimensions(b"not an image") is None, "dimensions() must return None for junk, not crash"

    print("image_processing selftest: PASS")


if __name__ == "__main__":
    _selftest()

