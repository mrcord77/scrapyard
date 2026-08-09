"""
data_import_executor — Execute data import operations with transaction management and rollback support. Ensures data integrity during bulk imports using SQLAlchemy sessions and rollback on failure.

### PART-META-JSON
{
  "name": "data_import_executor",
  "layer": "data_io",
  "purpose": "Execute data import operations with transaction management and rollback support. Ensures data integrity during bulk imports using SQLAlchemy sessions and rollback on failure.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: ImportError(...); ValidationError(...); ImportPolicy(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.data_io.data_import_executor`.",
  "example": "from scrapyard.data_io.data_import_executor import *",
  "import_path": "scrapyard.data_io.data_import_executor"
}
### END-PART-META
"""

import logging
import time
from typing import List, Dict, Any, Optional, Callable, Type
from sqlalchemy import String, Integer, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
import tempfile
import os

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class ImportError(Exception):
    """Raised when import operation fails and is rolled back."""
    pass


class ValidationError(Exception):
    """Raised when data validation fails."""
    pass


class ImportPolicy:
    UPSERT = "upsert"
    REPLACE = "replace"
    SKIP = "skip"


class ImportExecutor:
    """Execute data import operations with transaction management and rollback support."""
    
    def __init__(
        self,
        model_class: Type,
        validator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        policy: str = ImportPolicy.UPSERT,
        batch_size: int = 100,
        unique_key: Optional[str] = None
    ):
        self.model_class = model_class
        self.validator = validator
        self.policy = policy
        self.batch_size = batch_size
        self.unique_key = unique_key
        self.logger = logging.getLogger(__name__)
    
    def execute_import(self, data: List[dict], session: Session) -> None:
        """
        Execute import with full transaction rollback on failure.
        
        Args:
            data: List of dictionaries to import
            session: SQLAlchemy session
            
        Raises:
            ImportError: If import fails and is rolled back
        """
        if not data:
            return
        
        processed = 0
        failed = 0
        
        try:
            for i, row in enumerate(data):
                try:
                    # Validate and transform if validator provided
                    if self.validator:
                        row = self.validator(row)
                    
                    # Prepare instance based on policy
                    instance = self._prepare_instance(row, session)
                    session.add(instance)
                    processed += 1
                    
                    # Progress logging
                    if self.batch_size > 0 and (i + 1) % self.batch_size == 0:
                        self.logger.info(f"Processed {i + 1}/{len(data)} rows")
                        
                except Exception as e:
                    failed += 1
                    self.logger.error(f"Row {i} validation error: {e}")
                    if self.policy == ImportPolicy.SKIP:
                        continue
                    else:
                        raise
            
            # Commit all successful rows
            session.commit()
            self.logger.info(f"Import completed: {processed} processed, {failed} failed")
            
        except Exception as e:
            session.rollback()
            self.logger.error(f"Import rolled back due to error: {e}")
            raise ImportError(f"Import failed: {e}") from e
    
    def _prepare_instance(self, data: Dict[str, Any], session: Session) -> Any:
        """Create new instance or update existing based on policy."""
        if self.policy == ImportPolicy.UPSERT and self.unique_key:
            # Check for existing record
            existing = session.execute(
                select(self.model_class).where(
                    getattr(self.model_class, self.unique_key) == data.get(self.unique_key)
                )
            ).scalar_one_or_none()
            
            if existing:
                # Update existing record
                for key, value in data.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                return existing
        
        # Create new instance
        return self.model_class(**data)


def _selftest():
    """Module self-test verifying transaction management and performance."""
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        class TestModel(IntPKModel):
            __tablename__ = "data_import_executor_test_items"
            name: Mapped[str] = mapped_column(String(100), nullable=False)
            value: Mapped[int] = mapped_column(Integer, default=0)
        
        IntPKModel.metadata.create_all(engine)
        SessionFactory = sessionmaker(bind=engine)
        
        # Test 1: Basic insertion with commit
        session = SessionFactory()
        try:
            executor = ImportExecutor(TestModel)
            executor.execute_import([{"name": "a", "value": 1}, {"name": "b", "value": 2}], session)
            assert session.query(TestModel).count() == 2
        finally:
            session.close()
        
        # Test 2: Transaction rollback on validation error
        session = SessionFactory()
        try:
            def strict_validator(row):
                if not isinstance(row.get("value"), int):
                    raise ValidationError("Value must be int")
                return row
            
            executor = ImportExecutor(TestModel, validator=strict_validator)
            try:
                executor.execute_import([{"name": "c", "value": "invalid"}], session)
                assert False, "Should have raised ImportError"
            except ImportError:
                pass
            
            # Verify rollback occurred
            assert session.query(TestModel).count() == 2
        finally:
            session.close()
        
        # Test 3: Skip policy - error logging without crash, partial commit
        session = SessionFactory()
        try:
            errors = []
            class MockLogger:
                def error(self, msg): errors.append(msg)
                def info(self, msg): pass
            
            def validate_int(row):
                if not isinstance(row.get("value"), int):
                    raise ValueError("Not int")
                return row
            
            executor = ImportExecutor(TestModel, validator=validate_int, policy=ImportPolicy.SKIP)
            executor.logger = MockLogger()
            
            # Mixed valid/invalid data
            executor.execute_import([{"name": "c", "value": 3}, {"name": "d", "value": "bad"}], session)
            
            # Should have 3 items (2 original + 1 valid from this batch)
            assert session.query(TestModel).count() == 3
            assert len(errors) == 1  # One error logged for the bad row
        finally:
            session.close()
        
        # Test 4: Session isolation
        session1 = SessionFactory()
        session2 = SessionFactory()
        try:
            executor = ImportExecutor(TestModel)
            executor.execute_import([{"name": "iso", "value": 99}], session1)
            
            # Both sessions should see committed data
            assert session1.query(TestModel).count() == 4
            assert session2.query(TestModel).count() == 4
        finally:
            session1.close()
            session2.close()
        
        # Test 5: Type enforcement
        session = SessionFactory()
        try:
            def type_check(row):
                if not isinstance(row.get("name"), str):
                    raise TypeError("Name must be string")
                return row
            
            executor = ImportExecutor(TestModel, validator=type_check)
            
            # This should fail and rollback
            try:
                executor.execute_import([{"name": 123, "value": 1}], session)
                assert False, "Should raise"
            except ImportError:
                pass
            
            # Count unchanged
            assert session.query(TestModel).count() == 4
        finally:
            session.close()
        
        # Test 6: Performance with 1000+ records
        session = SessionFactory()
        try:
            executor = ImportExecutor(TestModel, batch_size=100)
            bulk = [{"name": f"item_{i}", "value": i} for i in range(1000)]
            
            start = time.time()
            executor.execute_import(bulk, session)
            elapsed = time.time() - start
            
            assert elapsed < 20, f"Too slow: {elapsed}s"
            assert session.query(TestModel).count() == 1004  # 4 + 1000
        finally:
            session.close()
        
        engine.dispose()


if __name__ == "__main__":
    _selftest()
