"""
sqlite_storage — SQLite-backed ORM tables for factory-intel workspace data.

### PART-META-JSON
{
  "name": "sqlite_storage",
  "layer": "factory_intel",
  "purpose": "SQLite backend for factory-intel workspace data: ORM models for files, directories, projects, dependencies, capabilities and reports, plus initialize_db and a small Store facade.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy"],
  "inputs": "A SQLite db_path for initialize_db; a SQLAlchemy Session for Store; model field values.",
  "outputs": "SQLite database file at db_path containing 6 tables: sqlitestorage_files, sqlitestorage_directories, sqlitestorage_projects, sqlitestorage_dependencies, sqlitestorage_capabilities, sqlitestorage_reports.",
  "files_created": ["<db_path> (SQLite database with tables sqlitestorage_files, sqlitestorage_directories, sqlitestorage_projects, sqlitestorage_dependencies, sqlitestorage_capabilities, sqlitestorage_reports)"],
  "security_notes": "All queries go through the SQLAlchemy ORM (parameterized - no raw SQL string building). db_path is a local file: place it outside web-served directories and do not store secrets in report_data JSON. Table names are part-prefixed to avoid cross-part collisions ('sqlite_' prefix avoided: reserved by SQLite).",
  "ai_usage": "initialize_db(path) once, then Session(create_engine(...)) and Store(session) for add_file/get_project; models are plain declarative classes on the shared IntPKModel base.",
  "example": "from scrapyard.factory_intel.sqlite_storage import initialize_db, Store, Project",
  "import_path": "scrapyard.factory_intel.sqlite_storage"
}
### END-PART-META
"""
from sqlalchemy import String, Integer, Text, DateTime, JSON, ForeignKey, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import os, logging, tempfile

logger = logging.getLogger(__name__)

def initialize_db(db_path: str) -> None:
    """Initialize and connect to SQLite database."""
    engine = create_engine(f"sqlite:///{db_path}")
    IntPKModel.metadata.create_all(engine)
    engine.dispose()

class Store:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_file(self, file: 'File') -> None:
        """Add a new file to the database."""
        self.session.add(file)
        self.session.commit()

    def get_project(self, project_id: int) -> Optional['Project']:
        """Retrieve a project by ID."""
        return self.session.get(Project, project_id)

class File(IntPKModel):
    __tablename__ = 'sqlitestorage_files'
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Directory(IntPKModel):
    __tablename__ = 'sqlitestorage_directories'
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)

class Project(IntPKModel):
    __tablename__ = 'sqlitestorage_projects'
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Dependency(IntPKModel):
    __tablename__ = 'sqlitestorage_dependencies'
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey('sqlitestorage_projects.id'), nullable=False)
    dependency_name: Mapped[str] = mapped_column(String(255), nullable=False)

class Capability(IntPKModel):
    __tablename__ = 'sqlitestorage_capabilities'
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

class Report(IntPKModel):
    __tablename__ = 'sqlitestorage_reports'
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey('sqlitestorage_projects.id'), nullable=False)
    report_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

def _selftest() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        initialize_db(db_path)

        # Test Store
        engine = create_engine(f"sqlite:///{db_path}")
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        try:
            store = Store(session)

            # Add files
            file1 = File(name='file1.txt', path='/path/to/file1.txt', size=1024)
            file2 = File(name='file2.txt', path='/path/to/file2.txt', size=2048)
            store.add_file(file1)
            store.add_file(file2)

            # Retrieve files
            assert session.query(File).count() == 2

            # Add and test directory
            dir1 = Directory(name='test_dir', path='/path/to/dir')
            session.add(dir1)
            session.commit()
            retrieved_dir = session.get(Directory, dir1.id)
            assert retrieved_dir is not None and retrieved_dir.name == 'test_dir'

            # Add project
            project = Project(name='TestProject')
            store.session.add(project)
            store.session.commit()

            # Retrieve project
            retrieved_project = store.get_project(project.id)
            assert retrieved_project is not None and retrieved_project.name == 'TestProject'

            # Add and test dependency
            dep = Dependency(project_id=project.id, dependency_name='numpy')
            session.add(dep)
            session.commit()
            retrieved_dep = session.get(Dependency, dep.id)
            assert retrieved_dep is not None and retrieved_dep.dependency_name == 'numpy'

            # Add and test capability
            cap = Capability(name='vision_processing')
            session.add(cap)
            session.commit()
            retrieved_cap = session.get(Capability, cap.id)
            assert retrieved_cap is not None and retrieved_cap.name == 'vision_processing'

            # Add and test report
            report = Report(project_id=project.id, report_data={'status': 'ok', 'score': 95})
            session.add(report)
            session.commit()
            retrieved_report = session.get(Report, report.id)
            assert retrieved_report is not None and retrieved_report.report_data['score'] == 95

            # Test delete on files
            session.delete(file1)
            session.commit()
            assert session.query(File).count() == 1

            # Test delete on all other tables
            session.delete(retrieved_dir)
            session.delete(retrieved_dep)
            session.delete(retrieved_cap)
            session.delete(retrieved_report)
            session.delete(retrieved_project)
            session.commit()
            
            assert session.query(Directory).count() == 0
            assert session.query(Dependency).count() == 0
            assert session.query(Capability).count() == 0
            assert session.query(Report).count() == 0
            assert session.query(Project).count() == 0

        finally:
            # Clean up
            session.close()
            engine.dispose()

if __name__ == '__main__':
    _selftest()
