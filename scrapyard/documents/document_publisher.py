"""
document_publisher — Publishes generated documents to real targets (local filesystem
writes, HTTP/HTTPS POST uploads) with every attempt logged to a SQLAlchemy audit table.

### PART-META-JSON
{
  "name": "document_publisher",
  "layer": "documents",
  "purpose": "Publishes document content to external destinations and audits every attempt: 'local' targets write bytes/str content to a destination path on disk, http(s):// targets POST the content via requests (octet-stream with X-Document-Id header), and custom targets can be registered as handler callables. Each attempt inserts a DocumentPublishLog row (document_id, target, success flag, timestamp) whether it succeeds or fails.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy",
    "scrapyard.database.base_model",
    "requests (HTTP targets only)"
  ],
  "inputs": "document_id, target ('local', an http(s) URL, or a registered handler name), content bytes/str, destination path for local publishes; a session factory for audit logging.",
  "outputs": "bool success per publish; DocumentPublishLog rows in the database; files at destination paths or HTTP uploads as side effects.",
  "files_created": [
    "Published documents at caller-specified destination paths (local target).",
    "document_publish_log table rows in the configured database."
  ],
  "security_notes": "Publishing is exfiltration by design - the http target POSTs document content to a caller-supplied URL, so an attacker-controlled target URL leaks the document (SSRF + data exfil); allowlist destinations for anything user-influenced. Local publishing writes to caller-supplied paths with no traversal guard; normalize/contain destination paths upstream. The audit log stores document ids and target strings (URLs may embed tokens in query params - avoid that). No auth is added to HTTP posts by default; pass headers explicitly if the endpoint needs credentials, and prefer HTTPS targets. Custom handlers execute caller code.",
  "ai_usage": "Publisher(Session).publish_document(doc_id, 'local', content=b'...', destination=path) or (doc_id, 'https://host/up', content=...). register_target(name, fn) for custom sinks.",
  "example": "from scrapyard.documents.document_publisher import Publisher",
  "import_path": "scrapyard.documents.document_publisher"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Union
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

# Module-level session factory for the convenience function
_session_factory: Optional[Callable[[], Session]] = None

DEFAULT_HTTP_TIMEOUT = 30.0


class DocumentPublishLog(IntPKModel):
    __tablename__ = 'document_publish_log'

    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'), index=True)
    target: Mapped[str] = mapped_column(String(255))
    status: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


def _publish_local(document_id: int, content: Union[bytes, str],
                   destination: str, **_: Any) -> None:
    """Write document content to a real file at `destination`."""
    if destination is None:
        raise ValueError("local publishing requires a destination path")
    if content is None:
        raise ValueError("local publishing requires document content")
    parent = os.path.dirname(os.path.abspath(destination))
    os.makedirs(parent, exist_ok=True)
    mode = "wb" if isinstance(content, (bytes, bytearray)) else "w"
    kwargs = {} if "b" in mode else {"encoding": "utf-8"}
    with open(destination, mode, **kwargs) as fh:
        fh.write(content)


def _publish_http(document_id: int, content: Union[bytes, str], url: str,
                  headers: Optional[Dict[str, str]] = None,
                  timeout: float = DEFAULT_HTTP_TIMEOUT,
                  http_post: Optional[Callable[..., Any]] = None, **_: Any) -> None:
    """POST document content to a real HTTP(S) endpoint.

    `http_post` allows dependency injection for offline tests; default is
    requests.post.
    """
    if content is None:
        raise ValueError("http publishing requires document content")
    body = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    hdrs = {"Content-Type": "application/octet-stream",
            "X-Document-Id": str(document_id)}
    if headers:
        hdrs.update(headers)
    if http_post is None:
        import requests
        http_post = requests.post
    resp = http_post(url, data=body, headers=hdrs, timeout=timeout)
    status_code = getattr(resp, "status_code", None)
    if status_code is None or not (200 <= status_code < 300):
        raise ConnectionError(
            f"HTTP publish to {url} failed with status {status_code}")


class Publisher:
    """Publishes documents to real targets, auditing every attempt."""

    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory
        self._handlers: Dict[str, Callable[..., None]] = {"local": _publish_local}

    def register_target(self, name: str, handler: Callable[..., None]) -> None:
        """Register a custom target handler(document_id, content, **kwargs)."""
        if not callable(handler):
            raise ValueError("handler must be callable")
        self._handlers[name] = handler

    def publish_document(self, document_id: int, target: str, *,
                         content: Optional[Union[bytes, str]] = None,
                         destination: Optional[str] = None,
                         headers: Optional[Dict[str, str]] = None,
                         http_post: Optional[Callable[..., Any]] = None,
                         timeout: float = DEFAULT_HTTP_TIMEOUT) -> bool:
        """Publish a document and log the attempt; returns success as bool.

        Targets: 'local' (writes `content` to `destination`), an http(s) URL
        (POSTs `content`), or any name registered via register_target.
        """
        with self.session_factory() as session:
            log_entry = DocumentPublishLog(
                document_id=document_id,
                target=target,
                status=False,
            )
            session.add(log_entry)
            try:
                if target in self._handlers:
                    self._handlers[target](document_id, content,
                                           destination=destination,
                                           headers=headers,
                                           http_post=http_post,
                                           timeout=timeout)
                elif target.lower().startswith(("http://", "https://")):
                    _publish_http(document_id, content, target, headers=headers,
                                  timeout=timeout, http_post=http_post)
                else:
                    raise ValueError(f"Unsupported target: {target}")

                log_entry.status = True
                logger.info("Successfully published document %s to %s",
                            document_id, target)
            except Exception as e:
                logger.error("Failed to publish document %s to %s: %s",
                             document_id, target, e)
                log_entry.status = False

            session.commit()
            return log_entry.status


def publish_document(document_id: int, target: str, **kwargs: Any) -> bool:
    """Publish a document using the module-level configured session factory."""
    if _session_factory is None:
        raise RuntimeError("Session factory not configured. Use Publisher class "
                           "directly or configure the module.")
    publisher = Publisher(_session_factory)
    return publisher.publish_document(document_id, target, **kwargs)


def _selftest():
    from sqlalchemy import create_engine, Table, Column
    from sqlalchemy.orm import sessionmaker

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        engine = create_engine(f'sqlite:///{db_path}')

        # documents table for the FK, in the same metadata
        if 'documents' not in DocumentPublishLog.metadata.tables:
            Table('documents', DocumentPublishLog.metadata,
                  Column('id', Integer, primary_key=True))
        DocumentPublishLog.metadata.create_all(engine)

        Session = sessionmaker(bind=engine)

        global _session_factory
        original_factory = _session_factory
        _session_factory = Session

        try:
            publisher = Publisher(Session)

            # 1. REAL local publish: content lands on disk
            dest = os.path.join(temp_dir, "out", "doc1.txt")
            ok = publisher.publish_document(1, "local", content="hello doc",
                                            destination=dest)
            assert ok is True, "Local publish should succeed"
            with open(dest, encoding="utf-8") as fh:
                assert fh.read() == "hello doc"

            # bytes content too
            dest2 = os.path.join(temp_dir, "out", "doc1.bin")
            assert publisher.publish_document(1, "local", content=b"\x00\x01",
                                              destination=dest2) is True
            with open(dest2, "rb") as fh:
                assert fh.read() == b"\x00\x01"

            # Local without destination fails honestly (logged, status False)
            assert publisher.publish_document(2, "local", content="x") is False

            # 2. HTTP publish via injected poster (offline test of the real path)
            posted = {}

            class _Resp:
                status_code = 201

            def fake_post(url, data=None, headers=None, timeout=None):
                posted.update(url=url, data=data, headers=headers, timeout=timeout)
                return _Resp()

            ok = publisher.publish_document(3, "https://example.com/upload",
                                            content="payload", http_post=fake_post)
            assert ok is True
            assert posted["url"] == "https://example.com/upload"
            assert posted["data"] == b"payload"
            assert posted["headers"]["X-Document-Id"] == "3"

            # HTTP failure status -> logged failure
            class _Fail:
                status_code = 500

            assert publisher.publish_document(
                4, "https://example.com/upload", content="p",
                http_post=lambda *a, **k: _Fail()) is False

            # 3. Unsupported target
            assert publisher.publish_document(5, "ftp://nope") is False

            # 4. Custom registered target
            captured = []
            publisher.register_target(
                "collector", lambda doc_id, content, **k: captured.append(
                    (doc_id, content)))
            assert publisher.publish_document(6, "collector", content="c6") is True
            assert captured == [(6, "c6")]

            # 5. Module-level function + audit rows
            dest3 = os.path.join(temp_dir, "out", "doc7.txt")
            assert publish_document(7, "local", content="seven",
                                    destination=dest3) is True

            with Session() as session:
                logs = session.execute(select(DocumentPublishLog)).scalars().all()
                by_doc = {}
                for entry in logs:
                    by_doc.setdefault(entry.document_id, []).append(entry)
                assert len(logs) == 8, f"Expected 8 audit rows, got {len(logs)}"
                assert all(e.status for e in by_doc[1])
                assert not by_doc[2][0].status
                assert by_doc[3][0].status and by_doc[3][0].target.startswith("https://")
                assert not by_doc[4][0].status
                assert not by_doc[5][0].status
                assert by_doc[6][0].status
                assert by_doc[7][0].status

            logger.info("Self-test passed successfully")
            print("document_publisher selftest: all tests passed")
        finally:
            _session_factory = original_factory
            engine.dispose()


if __name__ == "__main__":
    _selftest()
