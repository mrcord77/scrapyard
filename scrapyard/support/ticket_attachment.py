"""
ticket_attachment — ticket attachment

### PART-META-JSON
{
  "name": "ticket_attachment",
  "layer": "support",
  "purpose": "ticket attachment",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: upload_attachment(ticket_id, file, db_session); download_attachment(attachment_id, db_session); UploadFile(...); AttachmentType(...); Attachment(...).",
  "outputs": "Returns: upload_attachment -> Attachment; download_attachment -> bytes.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.ticket_attachment`.",
  "example": "from scrapyard.support.ticket_attachment import *",
  "import_path": "scrapyard.support.ticket_attachment"
}
### END-PART-META
"""
import logging
import os
import tempfile
from typing import Optional, Protocol

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class UploadFile(Protocol):
    """Protocol for file upload objects matching FastAPI UploadFile interface."""
    filename: str
    content_type: str
    
    def read(self, size: int = -1) -> bytes:
        """Read file contents as bytes."""
        ...


class AttachmentType(IntPKModel):
    """Classification types for attachments."""
    __tablename__ = "attachment_type"
    
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class Attachment(IntPKModel):
    """File attachment storage for support tickets."""
    __tablename__ = "attachment"
    
    ticket_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("attachment_type.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


def upload_attachment(ticket_id: int, file: UploadFile, db_session: Session) -> Attachment:
    """
    Upload an attachment for a ticket.
    
    Args:
        ticket_id: The ID of the ticket to attach the file to
        file: The file to upload (conforms to UploadFile protocol)
        db_session: SQLAlchemy database session
        
    Returns:
        The created Attachment record
    """
    logger.info(f"Uploading attachment for ticket {ticket_id}: {file.filename}")
    
    content = file.read()
    
    attachment = Attachment(
        ticket_id=ticket_id,
        type_id=1,
        filename=file.filename,
        content_type=file.content_type,
        data=content
    )
    
    db_session.add(attachment)
    db_session.commit()
    db_session.refresh(attachment)
    
    logger.info(f"Attachment uploaded successfully with id {attachment.id}")
    return attachment


def download_attachment(attachment_id: int, db_session: Session) -> bytes:
    """
    Download attachment bytes by ID.
    
    Args:
        attachment_id: The ID of the attachment to download
        db_session: SQLAlchemy database session
        
    Returns:
        The binary content of the attachment
        
    Raises:
        ValueError: If attachment is not found
    """
    logger.info(f"Downloading attachment {attachment_id}")
    
    stmt = select(Attachment).where(Attachment.id == attachment_id)
    attachment = db_session.execute(stmt).scalar_one_or_none()
    
    if attachment is None:
        logger.error(f"Attachment {attachment_id} not found")
        raise ValueError(f"Attachment with id {attachment_id} not found")
    
    logger.info(f"Attachment {attachment_id} retrieved, size {len(attachment.data)} bytes")
    return attachment.data


def _selftest() -> None:
    """
    Offline self-test using temporary SQLite database.
    
    Verifies upload/download, model mapping, attachment_type population,
    and type hints without network calls.
    """
    logger.info("Starting ticket_attachment self-test")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        IntPKModel.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        try:
            general_type = AttachmentType(id=1, name="General", description="General files")
            image_type = AttachmentType(name="Image", description="Image files")
            session.add_all([general_type, image_type])
            session.commit()
            
            types_result = session.execute(select(AttachmentType)).scalars().all()
            assert len(types_result) == 2, "Attachment_type table should have 2 entries"
            
            class MockUploadFile:
                def __init__(self, filename: str, content_type: str, data: bytes):
                    self.filename = filename
                    self.content_type = content_type
                    self._data = data
                
                def read(self, size: int = -1) -> bytes:
                    return self._data
            
            test_data = b"Test attachment content for scrapyard ticket system"
            mock_file = MockUploadFile("test.txt", "text/plain", test_data)
            
            attachment: Attachment = upload_attachment(123, mock_file, session)
            assert attachment.id is not None
            assert attachment.ticket_id == 123
            assert attachment.filename == "test.txt"
            assert attachment.content_type == "text/plain"
            assert attachment.data == test_data
            assert attachment.type_id == 1
            
            downloaded: bytes = download_attachment(attachment.id, session)
            assert downloaded == test_data
            
            try:
                download_attachment(99999, session)
                assert False, "Should raise ValueError for missing attachment"
            except ValueError:
                pass
            
            logger.info("Self-test passed: all assertions successful")
            
        finally:
            session.close()
            engine.dispose()
    
    logger.info("Self-test completed")


if __name__ == "__main__":
    _selftest()
