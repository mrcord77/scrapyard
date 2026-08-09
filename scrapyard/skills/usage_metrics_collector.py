"""
usage_metrics_collector — Collect and store metrics on skill usage for analysis and optimization. This module provides tools to record, track, and query skill usage data in a structured and scalable way.

### PART-META-JSON
{
  "name": "usage_metrics_collector",
  "layer": "skills",
  "purpose": "Collect and store metrics on skill usage for analysis and optimization. This module provides tools to record, track, and query skill usage data in a structured and scalable way.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure_database(database_url); record_usage(skill_id, context); get_skill_usage(skill_id); Base(...); UsageMetrics(...); SkillUsageAggregate(...).",
  "outputs": "Returns: configure_database -> None; record_usage -> None; get_skill_usage -> List[UsageMetrics].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.skills.usage_metrics_collector`.",
  "example": "from scrapyard.skills.usage_metrics_collector import *",
  "import_path": "scrapyard.skills.usage_metrics_collector"
}
### END-PART-META
"""

from sqlalchemy import String, Integer, DateTime, JSON, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, Session, DeclarativeBase, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import logging
import tempfile
import os

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class UsageMetrics(Base, IntPKModel):
    """ORM model for detailed usage logs stored in usage_logs table."""
    __tablename__ = "usage_logs"
    
    skill_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


class SkillUsageAggregate(Base, IntPKModel):
    """ORM model for aggregated usage statistics stored in skill_usages table."""
    __tablename__ = "skill_usages"
    
    skill_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


_engine: Optional[Any] = None
_Session: Optional[Any] = None


def _get_engine() -> Any:
    """Get or create the default database engine."""
    global _engine
    if _engine is None:
        _engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(_engine)
    return _engine


def configure_database(database_url: str) -> None:
    """Configure the database connection for the module."""
    global _engine, _Session
    _engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine)


def _get_session() -> Session:
    """Get a new database session."""
    global _Session
    if _Session is None:
        engine = _get_engine()
        _Session = sessionmaker(bind=engine)
    return _Session()


def record_usage(skill_id: str, context: Dict[str, Any]) -> None:
    """
    Record a skill usage event with timestamp and context.
    
    Args:
        skill_id: Unique identifier for the skill
        context: Dictionary containing execution context and metadata
    """
    session = _get_session()
    try:
        # Insert into usage_logs
        usage_entry = UsageMetrics(
            skill_id=skill_id,
            context=context
        )
        session.add(usage_entry)
        
        # Update or insert into skill_usages (aggregated)
        stmt = select(SkillUsageAggregate).where(SkillUsageAggregate.skill_id == skill_id)
        aggregate = session.execute(stmt).scalar_one_or_none()
        
        current_time = datetime.now(timezone.utc)
        
        if aggregate is None:
            aggregate = SkillUsageAggregate(
                skill_id=skill_id,
                usage_count=1,
                last_used=current_time
            )
            session.add(aggregate)
        else:
            aggregate.usage_count += 1
            aggregate.last_used = current_time
        
        session.commit()
        logger.debug(f"Recorded usage for skill '{skill_id}'")
        
    except Exception:
        session.rollback()
        logger.exception(f"Failed to record usage for skill '{skill_id}'")
        raise
    finally:
        session.close()


def get_skill_usage(skill_id: str) -> List[UsageMetrics]:
    """
    Retrieve usage metrics for a specific skill from usage_logs.
    
    Args:
        skill_id: Unique identifier for the skill
        
    Returns:
        List of UsageMetrics ordered by timestamp descending
    """
    session = _get_session()
    try:
        stmt = (
            select(UsageMetrics)
            .where(UsageMetrics.skill_id == skill_id)
            .order_by(UsageMetrics.timestamp.desc())
        )
        result = session.execute(stmt).scalars().all()
        return list(result)
    finally:
        session.close()


def _selftest() -> None:
    """
    Self-test using temporary SQLite database.
    Verifies record_usage inserts into usage_logs and UsageMetrics queries work.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db_url = f"sqlite:///{db_path}"
        
        test_engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(test_engine)
        TestSession = sessionmaker(bind=test_engine)
        
        global _engine, _Session
        original_engine = _engine
        original_session = _Session
        
        try:
            _engine = test_engine
            _Session = TestSession
            
            test_skill = "sandboxed_skill.test"
            ctx1 = {"executor": "sandbox", "input": "test1"}
            ctx2 = {"executor": "sandbox", "input": "test2"}
            
            # Test record_usage
            record_usage(test_skill, ctx1)
            record_usage(test_skill, ctx2)
            
            # Test get_skill_usage returns expected data
            usages = get_skill_usage(test_skill)
            assert len(usages) == 2, f"Expected 2 records, got {len(usages)}"
            assert all(isinstance(u, UsageMetrics) for u in usages)
            assert usages[0].skill_id == test_skill
            assert usages[1].skill_id == test_skill
            assert usages[0].timestamp >= usages[1].timestamp
            
            # Verify context preserved
            contexts = [u.context for u in usages]
            assert ctx1 in contexts
            assert ctx2 in contexts
            
            # Verify aggregated table
            with TestSession() as s:
                agg = s.execute(
                    select(SkillUsageAggregate).where(SkillUsageAggregate.skill_id == test_skill)
                ).scalar_one()
                assert agg.usage_count == 2
                assert agg.last_used is not None
            
            logger.info("usage_metrics_collector _selftest passed")
            
        finally:
            _engine = original_engine
            _Session = original_session
            test_engine.dispose()


if __name__ == "__main__":
    _selftest()
