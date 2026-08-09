"""
uploads — Validated multipart upload handling.

### PART-META-JSON
{
  "name": "uploads",
  "layer": "files",
  "purpose": "Validated multipart upload handling.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Public API: validate_upload(filename, content_type, size, *, max_bytes, allowed, policies); store_upload(storage, key, data, content_type, *, max_bytes, audit_log, metrics); bulk_store_uploads(storage, items, *, max_bytes, audit_log, metrics); log_audit_event(key, content_type, size); log_audit_events(events); UploadError(...); UploadPolicy(...); UploadItem(...) (plus more).",
  "outputs": "Returns: validate_upload -> None; store_upload -> str; bulk_store_uploads -> List[UploadResult]; log_audit_event -> None; log_audit_events -> None.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `validate_upload` from `scrapyard.files.uploads` and call it as shown in `example`; run `py -m scrapyard.files.uploads` to see its offline selftest.",
  "example": "from scrapyard.files.uploads import validate_upload",
  "import_path": "scrapyard.files.uploads"
}
### END-PART-META
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict

from typing import Any, List, Optional, Set
from pydantic import BaseModel

STATUS = "core"

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "application/pdf", "text/plain"}

class UploadError(ValueError):
    pass

class UploadPolicy(BaseModel):
    max_files_per_user: int = 10
    max_total_size: int = 5 * 1024 * 1024 * 1024  # 5GB
    allowed_content_types: Set[str] = ALLOWED_TYPES
    allowed_extensions: Set[str] = {"png", "jpg", "jpeg", "webp", "pdf", "txt"}

class UploadItem(BaseModel):
    filename: str
    content_type: str
    data: bytes
    user_id: Optional[str]

class UploadResult(BaseModel):
    key: str
    size: int
    status: str
    error: Optional[str] = None

class UploadStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"

class UploadStorage(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes) -> str:
        pass

    @abstractmethod
    def get(self, key: str) -> Optional[bytes]:
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        pass

def validate_upload(
    filename: str,
    content_type: str,
    size: int,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    allowed: Optional[Set[str]] = None,
    policies: Optional[List[UploadPolicy]] = None
) -> None:
    allowed = allowed or ALLOWED_TYPES
    if content_type not in allowed:
        raise UploadError(f"content type not allowed: {content_type}")
    if size > max_bytes:
        raise UploadError(f"file too large: {size} > {max_bytes}")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise UploadError("unsafe filename")

def store_upload(
    storage: UploadStorage,
    key: str,
    data: bytes,
    content_type: str,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    audit_log: bool = True,
    metrics: bool = True
) -> str:
    validate_upload(key, content_type, len(data), max_bytes=max_bytes)
    key = storage.put(key, data)
    if audit_log:
        log_audit_event(key, content_type, len(data))
    if metrics:
        emit_metric("upload_success", 1)
    return key

def bulk_store_uploads(
    storage: UploadStorage,
    items: List[UploadItem],
    *,
    max_bytes: int = 10 * 1024 * 1024,
    audit_log: bool = True,
    metrics: bool = True
) -> List[UploadResult]:
    results = []
    for item in items:
        try:
            key = store_upload(storage, item.filename, item.data, item.content_type, max_bytes=max_bytes)
            results.append(UploadResult(key=key, size=len(item.data), status=UploadStatus.SUCCESS))
        except UploadError as e:
            results.append(UploadResult(key=item.filename, size=len(item.data), status=UploadStatus.FAILURE, error=str(e)))
    if audit_log:
        log_audit_events([(item.filename, item.content_type, len(item.data)) for item in items])
    if metrics:
        emit_metrics({"upload_success": len(results), "upload_failure": len([r for r in results if r.status == UploadStatus.FAILURE])})
    return results

def log_audit_event(key: str, content_type: str, size: int) -> None:
    import logging
    logging.getLogger("scrapyard.files.uploads").info(
        "upload audit key=%s content_type=%s size=%d", key, content_type, size)

def log_audit_events(events: List[tuple]) -> None:
    for key, content_type, size in events:
        log_audit_event(key, content_type, size)

def emit_metric(name: str, value: int) -> None:
    import logging
    logging.getLogger("scrapyard.files.uploads.metrics").debug("%s=%d", name, value)

def emit_metrics(data: Dict[str, Any]) -> None:
    for name, value in data.items():
        emit_metric(name, int(value))


def _selftest() -> bool:
    class MemStorage(UploadStorage):
        def __init__(self):
            self.blobs: Dict[str, bytes] = {}

        def put(self, key: str, data: bytes) -> str:
            self.blobs[key] = data
            return key

        def get(self, key: str) -> Optional[bytes]:
            return self.blobs.get(key)

        def delete(self, key: str) -> None:
            self.blobs.pop(key, None)

    st = MemStorage()
    assert store_upload(st, "a.txt", b"hi", "text/plain") == "a.txt"
    assert st.get("a.txt") == b"hi"
    for bad in (("../x.txt", "text/plain", 1), ("x.exe", "application/x-msdownload", 1),
                ("big.txt", "text/plain", 99 * 1024 * 1024)):
        try:
            validate_upload(*bad)
            raise AssertionError(f"accepted {bad}")
        except UploadError:
            pass
    items = [UploadItem(filename="ok.txt", content_type="text/plain", data=b"1", user_id=None),
             UploadItem(filename="bad.bin", content_type="application/zip", data=b"2", user_id=None)]
    results = bulk_store_uploads(st, items)
    assert results[0].status == UploadStatus.SUCCESS
    assert results[1].status == UploadStatus.FAILURE and results[1].error
    assert UploadStatus.SUCCESS.value == "success"  # real enum.Enum, not sqlalchemy type
    print("uploads selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
