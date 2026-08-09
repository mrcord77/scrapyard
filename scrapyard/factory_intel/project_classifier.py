"""
project_classifier — ** Classifies subprojects into predefined categories for structured factory intelligence. Enables automated categorization of codebases for reuse, maintenance, and deployment planning.

### PART-META-JSON
{
  "name": "project_classifier",
  "layer": "factory_intel",
  "purpose": "Classifies subprojects into predefined categories for structured factory intelligence. Enables automated categorization of codebases for reuse, maintenance, and deployment planning.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: classify_project(path); Classifier(...).",
  "outputs": "Returns: classify_project -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.factory_intel.project_classifier`.",
  "example": "from scrapyard.factory_intel.project_classifier import *",
  "import_path": "scrapyard.factory_intel.project_classifier"
}
### END-PART-META
"""
import os
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

from sqlalchemy import String, JSON, DateTime, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

CATEGORY_LIBRARY = "library"
CATEGORY_SERVICE = "service"
CATEGORY_SWARM = "swarm"
CATEGORY_SCRIPT = "script"
CATEGORY_UNKNOWN = "unknown"


class Classifier(IntPKModel):
    """ORM model for project classification results."""
    
    __tablename__ = "project_classifier_projects"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False, unique=True, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default=CATEGORY_UNKNOWN)
    meta: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )
    
    def classify(self, path: str) -> Dict[str, Any]:
        """Analyze project at path and populate instance fields.
        
        Args:
            path: Filesystem path to the project directory
            
        Returns:
            Dictionary containing classification results
        """
        result = classify_project(path)
        self.name = result["name"]
        self.path = result["path"]
        self.category = result["category"]
        self.meta = result.get("meta", {})
        return result


def classify_project(path: str) -> Dict[str, Any]:
    """Classify a project based on its filesystem structure.
    
    Args:
        path: Filesystem path to the project directory
        
    Returns:
        Dictionary with keys: name, path, category, indicators, meta
        
    Raises:
        FileNotFoundError: If path does not exist
    """
    path_obj = Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    
    files: Set[str] = {f.name for f in path_obj.iterdir() if f.is_file()}
    
    # Check for Python files, excluding packaging metadata
    excluded_meta_files = {"setup.py", "pyproject.toml"}
    python_files = {f for f in files if f.endswith(".py")} - excluded_meta_files
    has_python = bool(python_files)
    
    # Priority: Swarm > Service > Library > Script > Unknown
    category = CATEGORY_UNKNOWN
    indicators: list[str] = []
    
    if "swarm.yml" in files or "swarm.yaml" in files:
        category = CATEGORY_SWARM
        indicators.append("swarm_config")
    elif "Dockerfile" in files or "docker-compose.yml" in files or "docker-compose.yaml" in files:
        category = CATEGORY_SERVICE
        indicators.append("container_config")
    elif "setup.py" in files or "pyproject.toml" in files:
        category = CATEGORY_LIBRARY
        indicators.append("packaging")
    elif has_python:
        category = CATEGORY_SCRIPT
        indicators.append("python_files")
    
    file_count = len(list(path_obj.iterdir()))
    
    return {
        "name": path_obj.name,
        "path": str(path_obj.resolve()),
        "category": category,
        "indicators": indicators,
        "meta": {
            "file_count": file_count,
            "has_python": has_python,
            "detected_files": list(files)[:10]  # Limit stored metadata
        }
    }


def _selftest() -> bool:
    """Offline self-test using temporary SQLite database.
    
    Returns:
        True if all tests pass
        
    Raises:
        AssertionError: If any test fails
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Create test project structures
        lib_path = os.path.join(tmpdir, "my_library")
        svc_path = os.path.join(tmpdir, "my_service")
        swarm_path = os.path.join(tmpdir, "my_swarm")
        script_path = os.path.join(tmpdir, "my_script")
        empty_path = os.path.join(tmpdir, "empty_project")
        
        for p in [lib_path, svc_path, swarm_path, script_path, empty_path]:
            os.makedirs(p, exist_ok=True)
        
        # Library project
        with open(os.path.join(lib_path, "setup.py"), "w") as f:
            f.write("from setuptools import setup\nsetup(name='my_library')")
        with open(os.path.join(lib_path, "README.md"), "w") as f:
            f.write("# My Library")
        
        # Service project
        with open(os.path.join(svc_path, "Dockerfile"), "w") as f:
            f.write("FROM python:3.11-slim")
        with open(os.path.join(svc_path, "main.py"), "w") as f:
            f.write("import uvicorn")
        
        # Swarm project
        with open(os.path.join(swarm_path, "swarm.yml"), "w") as f:
            f.write("version: '3.8'\nservices:\n  app:\n    image: test")
        with open(os.path.join(swarm_path, "deploy.sh"), "w") as f:
            f.write("#!/bin/bash")
        
        # Script project
        with open(os.path.join(script_path, "utils.py"), "w") as f:
            f.write("def helper():\n    pass")
        with open(os.path.join(script_path, "run.py"), "w") as f:
            f.write("if __name__ == '__main__':\n    pass")
        
        # Test classify_project function
        lib_result = classify_project(lib_path)
        assert lib_result["category"] == CATEGORY_LIBRARY, f"Expected library, got {lib_result['category']}"
        assert lib_result["name"] == "my_library"
        assert "packaging" in lib_result["indicators"]
        
        svc_result = classify_project(svc_path)
        assert svc_result["category"] == CATEGORY_SERVICE, f"Expected service, got {svc_result['category']}"
        assert "container_config" in svc_result["indicators"]
        
        swarm_result = classify_project(swarm_path)
        assert swarm_result["category"] == CATEGORY_SWARM, f"Expected swarm, got {swarm_result['category']}"
        assert "swarm_config" in swarm_result["indicators"]
        
        script_result = classify_project(script_path)
        assert script_result["category"] == CATEGORY_SCRIPT, f"Expected script, got {script_result['category']}"
        assert script_result["meta"]["has_python"] is True
        
        empty_result = classify_project(empty_path)
        assert empty_result["category"] == CATEGORY_UNKNOWN, f"Expected unknown, got {empty_result['category']}"
        
        # Test Classifier ORM persistence
        db_file = os.path.join(tmpdir, "test_classifications.db")
        engine = create_engine(f"sqlite:///{db_file}", echo=False)
        IntPKModel.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        try:
            # Test classification and persistence
            classifier = Classifier()
            result = classifier.classify(lib_path)
            session.add(classifier)
            session.commit()
            
            # Verify persistence
            stmt = select(Classifier).where(Classifier.path == lib_path)
            persisted = session.execute(stmt).scalar_one_or_none()
            assert persisted is not None, "Classifier instance was not persisted"
            assert persisted.category == CATEGORY_LIBRARY
            assert persisted.name == "my_library"
            assert persisted.meta is not None
            assert persisted.meta.get("has_python") is False
            
            # Test another classification
            svc_classifier = Classifier()
            svc_result = svc_classifier.classify(svc_path)
            session.add(svc_classifier)
            session.commit()
            
            # Query all projects
            all_projects = session.execute(select(Classifier)).scalars().all()
            assert len(all_projects) == 2, f"Expected 2 projects, found {len(all_projects)}"
            
            # Verify categories are stored correctly
            categories = {p.category for p in all_projects}
            assert CATEGORY_LIBRARY in categories
            assert CATEGORY_SERVICE in categories
            
        finally:
            session.close()
            engine.dispose()
    
    return True
