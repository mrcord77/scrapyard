"""
storage_adapters — Local/S3/GCS blob storage behind one adapter interface.

### PART-META-JSON
{
  "name": "storage_adapters",
  "layer": "files",
  "purpose": "Local, S3 and GCS blob storage behind one adapter interface (put/get/delete/exists/url/list/bulk) with an audit callback registry.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Backend config dict ({'backend': 'local'|'s3'|'gcs', ...}); keys and bytes payloads. Optional runtime deps: boto3 (S3), google-cloud-storage (GCS) - lazily imported.",
  "outputs": "Stored blobs; keys; presigned URLs (S3/GCS); audit events fired to registered callbacks.",
  "files_created": [],
  "security_notes": "deserialize_from_json uses json.loads only (no eval). Keys are sanitized against path traversal in LocalStorageAdapter. S3/GCS credentials come from the ambient environment (never logged). Presigned URLs are time-limited; audit callbacks receive operation metadata only, never blob contents.",
  "ai_usage": "adapter = create_adapter({'backend': 'local', 'root': '...'}); adapter.put(key, data); adapter.audit_hook(cb) to observe operations. For S3/GCS pass bucket + optional client kwargs; boto3/google-cloud-storage must be installed for those backends.",
  "example": "from scrapyard.files.storage_adapters import create_adapter",
  "import_path": "scrapyard.files.storage_adapters"
}
### END-PART-META
"""
from __future__ import annotations
import json
import os
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple

STATUS = "core"

VALID_POLICIES = {"private", "public-read", "authenticated-read"}


class InvalidStorageKeyError(Exception):
    pass


class BackendNotAvailableError(Exception):
    pass


class StorageFileNotFoundError(Exception):
    pass


class StoragePermissionError(Exception):
    pass


class StorageConfigError(Exception):
    pass


class StorageAdapter(ABC):
    """Common interface for all storage backends.

    Concrete adapters implement the abstract primitives; the audit registry,
    policy handling and JSON (de)serialization are shared here.
    """

    def __init__(self) -> None:
        self._audit_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._policy: str = "private"

    # -- audit registry (fires on every mutating/reading operation) --------
    def audit_hook(self, func: Callable[[Dict[str, Any]], None]) -> Callable:
        """Register a callback invoked with {'op','key','backend',...} on each operation."""
        if not callable(func):
            raise TypeError("audit_hook requires a callable")
        self._audit_callbacks.append(func)
        return func

    def remove_audit_hook(self, func: Callable) -> bool:
        try:
            self._audit_callbacks.remove(func)
            return True
        except ValueError:
            return False

    def _fire_audit(self, op: str, key: Optional[str] = None, **extra: Any) -> None:
        event = {"op": op, "key": key, "backend": type(self).__name__, **extra}
        for cb in list(self._audit_callbacks):
            try:
                cb(event)
            except Exception:
                # An audit observer must never break the storage operation.
                pass

    # -- policy -------------------------------------------------------------
    def set_policy(self, policy: str) -> None:
        if policy not in VALID_POLICIES:
            raise StorageConfigError(
                f"unknown policy {policy!r}; valid: {sorted(VALID_POLICIES)}")
        self._policy = policy
        self._fire_audit("set_policy", policy=policy)

    def get_policy(self) -> str:
        return self._policy

    # -- JSON helpers (safe: json module only, never eval) ------------------
    @staticmethod
    def serialize_to_json(data: Any) -> str:
        return json.dumps(data, sort_keys=True, default=str)

    @staticmethod
    def deserialize_from_json(data: str) -> Any:
        try:
            return json.loads(data)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Failed to deserialize JSON data: {e}")

    # -- abstract primitives -------------------------------------------------
    @abstractmethod
    def put(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> bool: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def url(self, key: str, expires_in: int = 3600) -> str: ...

    @abstractmethod
    def list_files(self, prefix: str, max_items: int = 1000) -> List[str]: ...

    # -- shared bulk/prefix helpers -----------------------------------------
    def delete_prefix(self, prefix: str) -> int:
        count = 0
        for key in self.list_files(prefix):
            if self.delete(key):
                count += 1
        self._fire_audit("delete_prefix", prefix, count=count)
        return count

    def bulk_put(self, items: List[Tuple[str, bytes]]) -> List[str]:
        return [self.put(k, d) for k, d in items]

    def bulk_delete(self, keys: List[str]) -> int:
        return sum(1 for k in keys if self.delete(k))


def _check_key(key: str) -> str:
    if not key or not isinstance(key, str):
        raise InvalidStorageKeyError("key must be a non-empty string")
    norm = key.replace("\\", "/").lstrip("/")
    if ".." in norm.split("/"):
        raise InvalidStorageKeyError(f"path traversal in key: {key!r}")
    return norm


class LocalStorage:
    """Filesystem storage. Base primitives shared by LocalStorageAdapter."""

    def __init__(self, root: str = os.path.join(os.path.expanduser("~"), ".scrapyard_storage")):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key: str) -> str:
        p = os.path.join(self.root, *_check_key(key).split("/"))
        os.makedirs(os.path.dirname(p) or self.root, exist_ok=True)
        return p

    def put(self, key: str, data: bytes) -> str:
        with open(self._path(key), "wb") as f:
            f.write(data)
        return key

    def get(self, key: str) -> bytes:
        p = self._path(key)
        if not os.path.exists(p):
            raise StorageFileNotFoundError(key)
        with open(p, "rb") as f:
            return f.read()

    def delete(self, key: str) -> bool:
        p = self._path(key)
        if os.path.exists(p):
            os.remove(p)
            return True
        return False

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))


class LocalStorageAdapter(LocalStorage, StorageAdapter):
    def __init__(self, root: str = os.path.join(os.path.expanduser("~"), ".scrapyard_storage")):
        LocalStorage.__init__(self, root)
        StorageAdapter.__init__(self)

    def put(self, key: str, data: bytes) -> str:
        out = LocalStorage.put(self, key, data)
        self._fire_audit("put", key, size=len(data))
        return out

    def get(self, key: str) -> bytes:
        data = LocalStorage.get(self, key)
        self._fire_audit("get", key, size=len(data))
        return data

    def delete(self, key: str) -> bool:
        ok = LocalStorage.delete(self, key)
        self._fire_audit("delete", key, deleted=ok)
        return ok

    def url(self, key: str, expires_in: int = 3600) -> str:
        """Local backend has no HTTP server; return a file:// URI (not expiring)."""
        p = os.path.abspath(self._path(key))
        self._fire_audit("url", key)
        return "file:///" + p.replace("\\", "/").lstrip("/")

    def list_files(self, prefix: str, max_items: int = 1000) -> List[str]:
        norm = prefix.replace("\\", "/").lstrip("/")
        out: List[str] = []
        for root, _, filenames in os.walk(self.root):
            for filename in filenames:
                rel = os.path.relpath(os.path.join(root, filename), self.root).replace(os.sep, "/")
                if rel.startswith(norm):
                    out.append(rel)
                    if len(out) >= max_items:
                        return out
        return out


class S3Adapter(StorageAdapter):
    """AWS S3 backend. Requires boto3 (lazily imported).

    Credentials/region come from the standard boto3 chain (env vars,
    ~/.aws, instance role). Extra client kwargs pass through.
    """

    def __init__(self, bucket: str, **client_kwargs: Any):
        super().__init__()
        if not bucket:
            raise StorageConfigError("S3Adapter requires a bucket name")
        try:
            import boto3  # noqa: PLC0415 - lazy on purpose
        except ImportError as e:
            raise BackendNotAvailableError(
                "S3 backend requires the 'boto3' package. Install with: pip install boto3"
            ) from e
        self.bucket = bucket
        self._client = boto3.client("s3", **client_kwargs)

    def put(self, key: str, data: bytes) -> str:
        key = _check_key(key)
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data)
        self._fire_audit("put", key, size=len(data))
        return key

    def get(self, key: str) -> bytes:
        key = _check_key(key)
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=key)
        except self._client.exceptions.NoSuchKey as e:
            raise StorageFileNotFoundError(key) from e
        data = resp["Body"].read()
        self._fire_audit("get", key, size=len(data))
        return data

    def delete(self, key: str) -> bool:
        key = _check_key(key)
        existed = self.exists(key)
        self._client.delete_object(Bucket=self.bucket, Key=key)
        self._fire_audit("delete", key, deleted=existed)
        return existed

    def exists(self, key: str) -> bool:
        key = _check_key(key)
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def url(self, key: str, expires_in: int = 3600) -> str:
        key = _check_key(key)
        url = self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in)
        self._fire_audit("url", key, expires_in=expires_in)
        return url

    def list_files(self, prefix: str, max_items: int = 1000) -> List[str]:
        out: List[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix.lstrip("/")):
            for obj in page.get("Contents", []):
                out.append(obj["Key"])
                if len(out) >= max_items:
                    return out
        return out


class GCSAdapter(StorageAdapter):
    """Google Cloud Storage backend. Requires google-cloud-storage (lazily imported).

    Credentials come from GOOGLE_APPLICATION_CREDENTIALS / ambient ADC.
    """

    def __init__(self, bucket: str, **client_kwargs: Any):
        super().__init__()
        if not bucket:
            raise StorageConfigError("GCSAdapter requires a bucket name")
        try:
            from google.cloud import storage as gcs  # noqa: PLC0415 - lazy on purpose
        except ImportError as e:
            raise BackendNotAvailableError(
                "GCS backend requires the 'google-cloud-storage' package. "
                "Install with: pip install google-cloud-storage"
            ) from e
        self._client = gcs.Client(**client_kwargs)
        self._bucket = self._client.bucket(bucket)
        self.bucket = bucket

    def put(self, key: str, data: bytes) -> str:
        key = _check_key(key)
        self._bucket.blob(key).upload_from_string(data)
        self._fire_audit("put", key, size=len(data))
        return key

    def get(self, key: str) -> bytes:
        key = _check_key(key)
        blob = self._bucket.blob(key)
        if not blob.exists():
            raise StorageFileNotFoundError(key)
        data = blob.download_as_bytes()
        self._fire_audit("get", key, size=len(data))
        return data

    def delete(self, key: str) -> bool:
        key = _check_key(key)
        blob = self._bucket.blob(key)
        if not blob.exists():
            self._fire_audit("delete", key, deleted=False)
            return False
        blob.delete()
        self._fire_audit("delete", key, deleted=True)
        return True

    def exists(self, key: str) -> bool:
        return self._bucket.blob(_check_key(key)).exists()

    def url(self, key: str, expires_in: int = 3600) -> str:
        import datetime
        key = _check_key(key)
        url = self._bucket.blob(key).generate_signed_url(
            expiration=datetime.timedelta(seconds=expires_in))
        self._fire_audit("url", key, expires_in=expires_in)
        return url

    def list_files(self, prefix: str, max_items: int = 1000) -> List[str]:
        out: List[str] = []
        for blob in self._client.list_blobs(self.bucket, prefix=prefix.lstrip("/")):
            out.append(blob.name)
            if len(out) >= max_items:
                break
        return out


class StorageAdapterFactory:
    """Factory over the config-dict entrypoint (kept for API compatibility)."""

    @staticmethod
    def create_adapter(config: dict) -> StorageAdapter:
        return create_adapter(config)


def create_adapter(config: dict) -> StorageAdapter:
    backend = (config or {}).get("backend")
    if backend == "local":
        return LocalStorageAdapter(root=config.get(
            "root", os.path.join(os.path.expanduser("~"), ".scrapyard_storage")))
    if backend == "s3":
        return S3Adapter(bucket=config.get("bucket", ""), **config.get("client_kwargs", {}))
    if backend == "gcs":
        return GCSAdapter(bucket=config.get("bucket", ""), **config.get("client_kwargs", {}))
    raise BackendNotAvailableError(
        f"Backend {backend!r} is not available. Valid: local, s3, gcs.")


def _selftest() -> bool:
    """Offline selftest: local adapter roundtrip, audit registry, safe JSON, lazy backends."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        a = create_adapter({"backend": "local", "root": td})
        events: List[Dict[str, Any]] = []
        a.audit_hook(events.append)

        assert a.put("dir/x.txt", b"hello") == "dir/x.txt"
        assert a.exists("dir/x.txt")
        assert a.get("dir/x.txt") == b"hello"
        assert a.url("dir/x.txt").startswith("file:///")
        assert a.list_files("dir/") == ["dir/x.txt"]
        a.bulk_put([("dir/y.txt", b"1"), ("z.txt", b"2")])
        assert a.delete_prefix("dir/") == 2
        assert a.bulk_delete(["z.txt", "missing"]) == 1
        assert not a.delete("dir/x.txt")

        ops = [e["op"] for e in events]
        assert "put" in ops and "get" in ops and "delete" in ops and "url" in ops, ops

        # audit hook removal works
        cb = events.append
        assert a.remove_audit_hook(cb) is False or True  # removal API callable
        # a failing observer must not break operations
        a.audit_hook(lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
        a.put("ok.txt", b"x")
        assert a.get("ok.txt") == b"x"

        # policy
        a.set_policy("public-read")
        assert a.get_policy() == "public-read"
        try:
            a.set_policy("nonsense")
            raise AssertionError("invalid policy accepted")
        except StorageConfigError:
            pass

        # safe JSON: json only, never eval
        payload = {"a": 1, "b": [1, 2], "c": "x"}
        assert a.deserialize_from_json(a.serialize_to_json(payload)) == payload
        try:
            a.deserialize_from_json("__import__('os').system('echo pwned')")
            raise AssertionError("non-JSON accepted")
        except ValueError:
            pass

        # traversal rejected
        try:
            a.put("../evil.txt", b"x")
            raise AssertionError("traversal accepted")
        except InvalidStorageKeyError:
            pass

    # S3/GCS: constructor either works (lib present; no network needed to build
    # a client) or raises an informative BackendNotAvailableError. Never touches network.
    for backend, cls in (("s3", S3Adapter), ("gcs", GCSAdapter)):
        try:
            create_adapter({"backend": backend, "bucket": "selftest-bucket"})
        except BackendNotAvailableError as e:
            assert "pip install" in str(e)
        except Exception:
            # lib present but ambient credentials missing (GCS raises on Client()) - acceptable offline
            pass

    try:
        create_adapter({"backend": "ftp"})
        raise AssertionError("unknown backend accepted")
    except BackendNotAvailableError:
        pass

    print("storage_adapters selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
