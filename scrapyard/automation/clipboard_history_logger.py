"""
clipboard_history_logger — Log all clipboard changes to a persistent history store for auditing or recovery. Enables tracking of user activity and content flow in automation workflows.

### PART-META-JSON
{
  "name": "clipboard_history_logger",
  "layer": "automation",
  "domain": "automation_windows",
  "purpose": "Log all clipboard changes to a persistent SQLite history store (SQLAlchemy ORM) with user attribution and timestamps, for auditing or recovery in automation workflows. Supports an opt-in content transform hook (encrypt/redact) applied before anything touches disk.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy",
    "scrapyard.database.base_model"
  ],
  "inputs": "Clipboard text content and a user label per change; a database path via _configure_database; optionally a transform callable (str -> str) via set_content_transform.",
  "outputs": "Rows in the clipboard_history SQLite table (content, user, timestamp).",
  "files_created": [
    "SQLite database at the caller-supplied db_path."
  ],
  "security_notes": "CAPTURE RISK - this part persists RAW CLIPBOARD CONTENTS to disk, and clipboards routinely carry passwords from password managers, 2FA codes, API keys, and PII. The history database is effectively a credential log: store it only on encrypted/ACL-restricted storage, keep retention short (delete rows aggressively; there is no automatic expiry), and get explicit consent before running this against another user's session - silent deployment is keylogger-adjacent surveillance. Opt-in mitigation: register a transform via set_content_transform() to encrypt or redact content BEFORE it is written; without it, everything is plaintext. Content is truncated to 1024 chars by schema but that does not reduce sensitivity.",
  "ai_usage": "Call _configure_database(db_path) once, optionally set_content_transform(encrypt_fn), then log_clipboard_change(content, user) per change.",
  "example": "from scrapyard.automation.clipboard_history_logger import log_clipboard_change",
  "import_path": "scrapyard.automation.clipboard_history_logger"
}
### END-PART-META
"""
from sqlalchemy import create_engine, String, DateTime, func, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from dataclasses import dataclass
from typing import Callable, Optional
import os, logging, tempfile, time

logger = logging.getLogger(__name__)

# Module-level engine and session factory (unconfigured at import)
_engine = None
Session = None

# Opt-in transform (e.g. encryption or redaction) applied to content BEFORE
# persistence. Set to None to store plaintext (the default - see security_notes).
_content_transform: Optional[Callable[[str], str]] = None


def set_content_transform(transform: Optional[Callable[[str], str]]) -> None:
    """Register a callable applied to clipboard content before it is stored.

    Use this to encrypt or redact sensitive content; pass None to clear.
    """
    global _content_transform
    if transform is not None and not callable(transform):
        raise ValueError("transform must be callable or None")
    _content_transform = transform

def _configure_database(db_path: str):
    """Configure the database engine and create tables."""
    global _engine, Session
    _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Session = sessionmaker(bind=_engine)
    IntPKModel.metadata.create_all(_engine)

class ClipboardHistory(IntPKModel):
    __tablename__ = 'clipboard_history'
    
    content: Mapped[str] = mapped_column(String(1024))
    user: Mapped[str] = mapped_column(String(50))
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

def log_clipboard_change(content: str, user: str = "system") -> None:
    if Session is None:
        raise RuntimeError("Database not configured")
    if _content_transform is not None:
        content = _content_transform(content)
    with Session() as session:
        clipboard_entry = ClipboardHistory(content=content, user=user)
        session.add(clipboard_entry)
        session.commit()

@dataclass
class ClipboardHistorySelfTest:
    db_path: str

    def create_table(self) -> bool:
        if Session is None:
            return False
        with Session() as session:
            try:
                session.execute(select(ClipboardHistory))
                return True
            except Exception as e:
                logger.error(f"Failed to select from clipboard_history table: {e}")
                return False

    def log_change(self, content: str, user: str = "system") -> bool:
        try:
            log_clipboard_change(content, user)
            return True
        except Exception as e:
            logger.error(f"Failed to log clipboard change: {e}")
            return False

    def check_timestamp_order(self) -> bool:
        if Session is None:
            return False
        with Session() as session:
            query = select(ClipboardHistory).order_by(ClipboardHistory.timestamp.asc())
            results = session.execute(query).scalars().all()
            timestamps = [entry.timestamp for entry in results]
            if len(timestamps) < 2:
                logger.error("Not enough entries to verify timestamp ordering")
                return False
            if all(timestamps[i] <= timestamps[i + 1] for i in range(len(timestamps) - 1)):
                return True
            else:
                logger.error("Timestamp order is incorrect")
                return False

    def check_user_context(self) -> bool:
        if Session is None:
            return False
        with Session() as session:
            query = select(ClipboardHistory).where(ClipboardHistory.user == "system")
            results = session.execute(query).scalars().all()
            if not results:
                logger.error("No entries found with user 'system'")
                return False
            if all(result.user == "system" for result in results):
                return True
            else:
                logger.error("User context is not preserved correctly")
                return False

    def run(self) -> bool:
        if not self.create_table():
            return False
        # Log multiple entries to test timestamp ordering
        if not self.log_change("First clipboard entry"):
            return False
        time.sleep(0.01)
        if not self.log_change("Second clipboard entry"):
            return False
        time.sleep(0.01)
        if not self.log_change("Third clipboard entry"):
            return False
        
        if not self.check_timestamp_order():
            return False
        if not self.check_user_context():
            return False
        logger.info("Self-test completed successfully")
        return True

def _selftest() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'clipboard_history.db')
        _configure_database(db_path)
        test = ClipboardHistorySelfTest(db_path)
        if not test.run():
            raise Exception("Self-test failed")

        # Opt-in transform hook: content is transformed before persistence
        set_content_transform(lambda s: f"REDACTED({len(s)})")
        try:
            log_clipboard_change("hunter2", user="hooked")
            with Session() as session:
                row = session.execute(
                    select(ClipboardHistory).where(ClipboardHistory.user == "hooked")
                ).scalars().one()
                assert row.content == "REDACTED(7)", row.content
                assert "hunter2" not in row.content
        finally:
            set_content_transform(None)

if __name__ == "__main__":
    _selftest()
