"""
file_walker — Walks and indexes all files and directories in a given workspace, providing a foundational dataset for project classification and analysis.

### PART-META-JSON
{
  "name": "file_walker",
  "layer": "factory_intel",
  "purpose": "Walks and indexes all files and directories in a given workspace, providing a foundational dataset for project classification and analysis.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: walk_and_index(workspace_path, session); FileMetadata(...); DirectoryMetadata(...); Indexer(...) (plus more).",
  "outputs": "Returns: walk_and_index -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.factory_intel.file_walker`.",
  "example": "from scrapyard.factory_intel.file_walker import *",
  "import_path": "scrapyard.factory_intel.file_walker"
}
### END-PART-META
"""

from sqlalchemy import String, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from dataclasses import dataclass
import os
import logging
import tempfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileMetadata:
    path: str
    size: int
    mtime: float
    type: str


@dataclass(frozen=True)
class DirectoryMetadata:
    path: str
    mtime: float


class Indexer:
    def __init__(self, session: Session):
        self.session = session

    def index_workspace(self, path: str) -> None:
        # Index the root directory itself
        self._index_directory(path)
        
        for root, dirs, files in os.walk(path):
            for name in files:
                file_path = os.path.join(root, name)
                try:
                    file_stat = os.stat(file_path)
                    file_metadata = FileMetadata(
                        path=file_path,
                        size=file_stat.st_size,
                        mtime=file_stat.st_mtime,
                        type='file'
                    )
                    self._add_to_session(file_metadata)
                except OSError as e:
                    logger.warning(f"Could not stat file {file_path}: {e}")

            for name in dirs:
                dir_path = os.path.join(root, name)
                self._index_directory(dir_path)

    def _index_directory(self, dir_path: str) -> None:
        try:
            dir_stat = os.stat(dir_path)
            dir_metadata = DirectoryMetadata(
                path=dir_path,
                mtime=dir_stat.st_mtime
            )
            self._add_to_session(dir_metadata)
        except OSError as e:
            logger.warning(f"Could not stat directory {dir_path}: {e}")

    def _add_to_session(self, metadata: FileMetadata | DirectoryMetadata) -> None:
        if isinstance(metadata, FileMetadata):
            file_table = FilesTable(
                path=metadata.path,
                size=metadata.size,
                mtime=datetime.fromtimestamp(metadata.mtime),
                type='file'
            )
            self.session.add(file_table)
        elif isinstance(metadata, DirectoryMetadata):
            dir_table = DirectoriesTable(
                path=metadata.path,
                mtime=datetime.fromtimestamp(metadata.mtime)
            )
            self.session.add(dir_table)


class FilesTable(IntPKModel):
    __tablename__ = 'file_walker_files'
    path: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    size: Mapped[int]
    mtime: Mapped[datetime]
    type: Mapped[str]


class DirectoriesTable(IntPKModel):
    __tablename__ = 'file_walker_directories'
    path: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    mtime: Mapped[datetime]


def walk_and_index(workspace_path: str, session: Session) -> None:
    indexer = Indexer(session)
    indexer.index_workspace(workspace_path)


def _selftest() -> None:
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        engine = create_engine('sqlite:///:memory:')
        FilesTable.metadata.create_all(engine)
        DirectoriesTable.metadata.create_all(engine)
        
        with Session(engine) as session:
            test_dir_path = os.path.join(temp_dir.name, 'test')
            os.makedirs(test_dir_path, exist_ok=True)
            for i in range(3):
                open(os.path.join(test_dir_path, f'file_{i}.txt'), 'a').close()
            os.makedirs(os.path.join(test_dir_path, 'subdir'), exist_ok=True)

            walk_and_index(test_dir_path, session)
            session.flush()

            files_query = select(FilesTable)
            dirs_query = select(DirectoriesTable)
            files_count = session.execute(files_query).scalars().all()
            dirs_count = session.execute(dirs_query).scalars().all()

            assert len(files_count) == 3, "Incorrect number of file entries"
            assert len(dirs_count) == 2, "Incorrect number of directory entries"
    finally:
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
