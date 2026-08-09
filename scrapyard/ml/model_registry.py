"""
model_registry — ** Maintain a centralized registry of machine learning models with metadata for serving and deployment. Enables discovery, versioning, and management of models across ML systems.

### PART-META-JSON
{
  "name": "model_registry",
  "layer": "ml",
  "purpose": "Maintain a centralized registry of machine learning models with metadata for serving and deployment. Enables discovery, versioning, and management of models across ML systems.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: add_model_to_registry(session, model_name, model_version, description, tags); get_model_from_registry(session, model_name, model_version); ModelRegistryEntry(...); ModelRegistry(...).",
  "outputs": "Returns: add_model_to_registry -> ModelRegistryEntry; get_model_from_registry -> Optional[ModelRegistryEntry].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.ml.model_registry`.",
  "example": "from scrapyard.ml.model_registry import *",
  "import_path": "scrapyard.ml.model_registry"
}
### END-PART-META
"""
from sqlalchemy import String, Text, JSON, select, create_engine, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, Session
from sqlalchemy.exc import IntegrityError
from scrapyard.database.base_model import IntPKModel
from dataclasses import dataclass, field
from typing import Optional, List
import os, logging, tempfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelRegistryEntry:
    model_name: str
    model_version: Optional[str]
    description: str
    tags: List[str] = field(default_factory=list)


class ModelRegistry(IntPKModel):
    __tablename__ = 'model_registry_table'
    __table_args__ = (UniqueConstraint('model_name', 'model_version'),)
    
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_version: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list)


def add_model_to_registry(
    session: Session,
    model_name: str,
    model_version: str,
    description: str,
    tags: Optional[List[str]] = None
) -> ModelRegistryEntry:
    if tags is None:
        tags = []
    
    registry_entry = ModelRegistry(
        model_name=model_name,
        model_version=model_version,
        description=description,
        tags=tags
    )
    session.add(registry_entry)
    session.commit()
    
    return ModelRegistryEntry(
        model_name=registry_entry.model_name,
        model_version=registry_entry.model_version,
        description=registry_entry.description,
        tags=registry_entry.tags
    )


def get_model_from_registry(
    session: Session,
    model_name: str,
    model_version: Optional[str] = None
) -> Optional[ModelRegistryEntry]:
    query = select(ModelRegistry).where(ModelRegistry.model_name == model_name)
    if model_version:
        query = query.where(ModelRegistry.model_version == model_version)
    
    result = session.execute(query).scalars().first()
    if result:
        return ModelRegistryEntry(
            model_name=result.model_name,
            model_version=model_version if model_version else None,
            description=result.description,
            tags=result.tags if result.tags else []
        )
    return None


def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'model_registry.db')
        engine = create_engine(f'sqlite:///{db_path}', echo=False)
        
        ModelRegistry.metadata.create_all(engine)
        
        with Session(bind=engine) as session:
            # Add model
            entry1 = add_model_to_registry(
                session,
                model_name='test_model',
                model_version='v1.0',
                description='Test model description',
                tags=['tag1', 'tag2']
            )
            assert isinstance(entry1, ModelRegistryEntry)
            
            # Get added model by name and version
            fetched_entry = get_model_from_registry(session, model_name='test_model', model_version='v1.0')
            assert fetched_entry.model_name == entry1.model_name
            assert fetched_entry.model_version == entry1.model_version
            assert fetched_entry.description == entry1.description
            assert set(fetched_entry.tags) == set(entry1.tags)
            
            # Attempt to add same version again (should fail due to unique constraint)
            try:
                add_model_to_registry(
                    session,
                    model_name='test_model',
                    model_version='v1.0',
                    description='Test model description v2'
                )
                assert False, "Expected IntegrityError but got success"
            except IntegrityError:
                session.rollback()
            
            # Get added model by name only
            fetched_entry = get_model_from_registry(session, model_name='test_model')
            assert fetched_entry.model_version is None

        engine.dispose()


if __name__ == '__main__':
    _selftest()
