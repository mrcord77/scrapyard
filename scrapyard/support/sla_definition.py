"""
sla_definition — ** Define service level agreements (SLAs) with structured metrics, targets, and timeframes. Supports creation, validation, and storage of SLA definitions for use in service management systems.

### PART-META-JSON
{
  "name": "sla_definition",
  "layer": "support",
  "purpose": "Define service level agreements (SLAs) with structured metrics, targets, and timeframes. Supports creation, validation, and storage of SLA definitions for use in service management systems.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_sla(name, description, metrics); validate_sla(sla); SLAMetric(...); SLADefinition(...).",
  "outputs": "Returns: create_sla -> SLADefinition; validate_sla -> bool.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.sla_definition`.",
  "example": "from scrapyard.support.sla_definition import *",
  "import_path": "scrapyard.support.sla_definition"
}
### END-PART-META
"""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import String, Float, Text, DateTime, func, ForeignKey, select
from sqlalchemy.orm import Mapped, mapped_column, relationship
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class SLAMetric(IntPKModel):
    """Represents a single metric target within an SLA definition."""
    __tablename__ = "sla_metrics"
    
    sla_id: Mapped[int] = mapped_column(ForeignKey("sla_definitions.id"), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(50), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    
    sla: Mapped["SLADefinition"] = relationship(back_populates="metrics")


class SLADefinition(IntPKModel):
    """Represents a Service Level Agreement definition with associated metrics."""
    __tablename__ = "sla_definitions"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    
    metrics: Mapped[List["SLAMetric"]] = relationship(
        back_populates="sla",
        cascade="all, delete-orphan"
    )


def create_sla(name: str, description: str, metrics: List[SLAMetric]) -> SLADefinition:
    """Create a new SLA definition with the specified metrics."""
    return SLADefinition(
        name=name,
        description=description,
        metrics=metrics
    )


def validate_sla(sla: SLADefinition) -> bool:
    """Validate that an SLA definition is complete and valid."""
    if not sla:
        return False
    
    if not sla.name or not isinstance(sla.name, str) or not sla.name.strip():
        return False
    
    if not sla.metrics or len(sla.metrics) == 0:
        return False
    
    for metric in sla.metrics:
        if not metric.metric_name or not isinstance(metric.metric_name, str) or not metric.metric_name.strip():
            return False
        if metric.target_value is None or not isinstance(metric.target_value, (int, float)):
            return False
        if not metric.timeframe or not isinstance(metric.timeframe, str) or not metric.timeframe.strip():
            return False
        if not metric.unit or not isinstance(metric.unit, str) or not metric.unit.strip():
            return False
    
    return True


def _selftest():
    """Run self-test with temporary SQLite database."""
    import tempfile
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "sla_test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        IntPKModel.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        try:
            metric1 = SLAMetric(
                metric_name="uptime",
                target_value=99.9,
                timeframe="monthly",
                unit="percent"
            )
            metric2 = SLAMetric(
                metric_name="response_time",
                target_value=200.0,
                timeframe="24h",
                unit="ms"
            )
            
            sla = create_sla(
                name="Premium SLA",
                description="High availability service",
                metrics=[metric1, metric2]
            )
            
            assert isinstance(sla, SLADefinition)
            assert sla.name == "Premium SLA"
            assert len(sla.metrics) == 2
            assert sla.metrics[0].metric_name == "uptime"
            
            # Use fresh metric instance to avoid detaching metric1 from sla
            invalid_empty_name = create_sla("", "desc", [SLAMetric(
                metric_name="uptime",
                target_value=99.9,
                timeframe="monthly",
                unit="percent"
            )])
            assert not validate_sla(invalid_empty_name)
            
            invalid_no_metrics = create_sla("No Metrics", "desc", [])
            assert not validate_sla(invalid_no_metrics)
            
            bad_metric = SLAMetric(metric_name="", target_value=50, timeframe="1h", unit="percent")
            invalid_bad_metric = create_sla("Bad", "desc", [bad_metric])
            assert not validate_sla(invalid_bad_metric)
            
            assert validate_sla(sla)
            
            session.add(sla)
            session.commit()
            
            assert sla.id is not None
            assert all(m.id is not None for m in sla.metrics)
            assert all(m.sla_id == sla.id for m in sla.metrics)
            
            loaded_sla = session.get(SLADefinition, sla.id)
            assert loaded_sla is not None
            assert loaded_sla.name == "Premium SLA"
            assert loaded_sla.description == "High availability service"
            assert len(loaded_sla.metrics) == 2
            
            metric_names = {m.metric_name for m in loaded_sla.metrics}
            assert "uptime" in metric_names
            assert "response_time" in metric_names
            
            stmt = select(SLAMetric).where(SLAMetric.sla_id == sla.id)
            db_metrics = session.execute(stmt).scalars().all()
            assert len(db_metrics) == 2
            
            assert loaded_sla.created_at is not None
            assert loaded_sla.updated_at is not None
            
        finally:
            session.close()
            engine.dispose()
    
    return True


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(1 if _selftest() is False else 0)
