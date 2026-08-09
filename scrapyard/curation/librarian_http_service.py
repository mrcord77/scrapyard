"""
librarian_http_service — Request/response persistence for the librarian: handle_request stores each metadata request and its composed response in SQLite with full audit linkage.

### PART-META-JSON
{
  "name": "librarian_http_service",
  "layer": "curation",
  "purpose": "Durable request/response layer for the librarian: handle_request persists the incoming RequestModel, composes a component bundle, stores the ResponseRecord linked by request_id, and respond_with_metadata retrieves metadata by UUID.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy"],
  "inputs": "RequestModel(part_name, layer, parameters); metadata UUIDs.",
  "outputs": "requests/responses rows in the librarian db; ResponseModel / MetadataResponse.",
  "files_created": ["librarian.db (or LIBRARIAN_DB_URL target)"],
  "security_notes": "Request payloads are persisted verbatim as JSON - callers must not put secrets in request parameters. DB URL comes from LIBRARIAN_DB_URL; point it at a local file, this layer does no authentication itself.",
  "ai_usage": "Import what you need from `scrapyard.curation.librarian_http_service`.",
  "example": "from scrapyard.curation.librarian_http_service import *",
  "import_path": "scrapyard.curation.librarian_http_service"
}
### END-PART-META
"""
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, String, create_engine, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

_engine = None


class RequestRecord(IntPKModel):
    __tablename__ = "requests"
    
    request_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    
    response: Mapped[Optional["ResponseRecord"]] = relationship(back_populates="request", uselist=False)


class ResponseRecord(IntPKModel):
    __tablename__ = "responses"
    
    metadata_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.request_id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    metadata_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    request: Mapped["RequestRecord"] = relationship(back_populates="response")


@dataclass
class RequestModel:
    part_name: Optional[str] = None
    layer: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResponseModel:
    request_id: str
    metadata_id: str
    status: str
    message: str = ""


@dataclass
class MetadataResponse:
    metadata_id: uuid.UUID
    data: Dict[str, Any]
    created_at: datetime


def _get_engine():
    global _engine
    if _engine is None:
        db_url = os.getenv("LIBRARIAN_DB_URL", "sqlite:///librarian.db")
        _engine = create_engine(db_url, echo=False, future=True)
        IntPKModel.metadata.create_all(_engine)
    return _engine


def build_metadata_composer(request: RequestModel) -> Dict[str, Any]:
    """Composes a component bundle based on the request parameters."""
    logger.debug(f"Building metadata for part: {request.part_name}")
    return {
        "part_name": request.part_name,
        "layer": request.layer,
        "composed_at": datetime.now(timezone.utc).isoformat(),
        "dependencies": [],
        "metadata": request.parameters
    }


def handle_request(request: RequestModel) -> ResponseModel:
    """Handle an incoming request by persisting it and generating a metadata."""
    engine = _get_engine()
    session = Session(engine)
    request_uuid = str(uuid.uuid4())
    metadata_uuid = str(uuid.uuid4())
    
    try:
        req_record = RequestRecord(
            request_id=request_uuid,
            payload=request.__dict__,
            status="processing"
        )
        session.add(req_record)
        session.flush()
        
        metadata_data = build_metadata_composer(request)
        
        resp_record = ResponseRecord(
            metadata_id=metadata_uuid,
            request_id=request_uuid,
            metadata_data=metadata_data
        )
        session.add(resp_record)
        
        req_record.status = "completed"
        session.commit()
        
        return ResponseModel(
            request_id=request_uuid,
            metadata_id=metadata_uuid,
            status="completed",
            message="Metadata generated successfully"
        )
    except Exception as e:
        session.rollback()
        logger.error(f"Error handling request: {e}")
        raise
    finally:
        session.close()


def respond_with_metadata(metadata_id: uuid.UUID) -> MetadataResponse:
    """Retrieve a metadata response by its UUID."""
    engine = _get_engine()
    session = Session(engine)
    try:
        stmt = select(ResponseRecord).where(ResponseRecord.metadata_id == str(metadata_id))
        result = session.execute(stmt).scalar_one_or_none()
        
        if result is None:
            raise ValueError(f"Metadata not found: {metadata_id}")
        
        return MetadataResponse(
            metadata_id=uuid.UUID(result.metadata_id),
            data=result.metadata_data,
            created_at=result.timestamp
        )
    finally:
        session.close()


def _selftest():
    """Offline self-test using temporary SQLite database."""
    import sqlite3
    
    global _engine
    original_engine = _engine
    
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = os.path.join(tmpdir, "test_librarian.db")
            db_url = f"sqlite:///{db_path}"
            
            _engine = create_engine(db_url, echo=False, future=True)
            IntPKModel.metadata.create_all(_engine)
            
            request = RequestModel(
                part_name="scrap_test_part",
                layer="curation",
                parameters={"force": True}
            )
            
            response = handle_request(request)
            assert response.status == "completed"
            assert len(response.request_id) == 36
            assert len(response.metadata_id) == 36
            
            metadata_id = uuid.UUID(response.metadata_id)
            metadata = respond_with_metadata(metadata_id)
            assert metadata.metadata_id == metadata_id
            assert metadata.data["part_name"] == "scrap_test_part"
            assert "composed_at" in metadata.data
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT request_id, status FROM requests")
            req_rows = cursor.fetchall()
            assert len(req_rows) == 1
            assert req_rows[0][0] == response.request_id
            assert req_rows[0][1] == "completed"
            
            cursor.execute("SELECT metadata_id, request_id FROM responses")
            resp_rows = cursor.fetchall()
            assert len(resp_rows) == 1
            assert resp_rows[0][0] == response.metadata_id
            assert resp_rows[0][1] == response.request_id
            
            cursor.execute("""
                SELECT r.request_id, s.metadata_id 
                FROM requests r 
                INNER JOIN responses s ON r.request_id = s.request_id
                WHERE r.status = 'completed'
            """)
            joined = cursor.fetchall()
            assert len(joined) == 1
            
            conn.close()
            logger.info("Selftest passed successfully")
            return True
            
    finally:
        if _engine:
            _engine.dispose()
        _engine = original_engine


if __name__ == "__main__":
    _selftest()
