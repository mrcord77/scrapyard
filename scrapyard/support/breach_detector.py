"""
breach_detector — Monitor and detect SLA breaches based on actual performance, providing actionable events for remediation and reporting.

### PART-META-JSON
{
  "name": "breach_detector",
  "layer": "support",
  "purpose": "Monitor and detect SLA breaches based on actual performance, providing actionable events for remediation and reporting.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: detect_breach(sla_rule, metrics); BreachType(...); BreachEvent(...); BreachDetector(...).",
  "outputs": "Returns: detect_breach -> List[BreachEvent].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.support.breach_detector`.",
  "example": "from scrapyard.support.breach_detector import *",
  "import_path": "scrapyard.support.breach_detector"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, create_engine, select, Enum
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from enum import Enum as PyEnum
import os
import json
import logging
import tempfile

logger = logging.getLogger(__name__)


class BreachType(str, PyEnum):
    LATENCY = "latency"
    UPTIME = "uptime"
    ERROR_RATE = "error_rate"


SLARule = Dict[str, Any]


class BreachEvent(IntPKModel):
    __tablename__ = "breach_events"
    
    breach_type: Mapped[BreachType] = mapped_column(Enum(BreachType))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[str] = mapped_column(String(500))


def detect_breach(sla_rule: SLARule, metrics: dict) -> List[BreachEvent]:
    """
    Detect breaches based on SLA rules and metrics.
    Returns list of BreachEvent objects (not persisted to DB).
    """
    breaches = []
    
    if 'latency' in sla_rule and sla_rule['latency'] is not None:
        threshold = sla_rule['latency']['threshold']
        metric_value = metrics.get('latency', 0)
        if metric_value > threshold:
            breaches.append(
                BreachEvent(
                    breach_type=BreachType.LATENCY, 
                    timestamp=datetime.now(timezone.utc), 
                    details=json.dumps({'metric': 'latency', 'value': metric_value, 'threshold': threshold})
                )
            )
    
    if 'uptime' in sla_rule and sla_rule['uptime'] is not None:
        threshold = sla_rule['uptime']['threshold']
        metric_value = metrics.get('uptime', 0)
        if metric_value < threshold:
            breaches.append(
                BreachEvent(
                    breach_type=BreachType.UPTIME, 
                    timestamp=datetime.now(timezone.utc), 
                    details=json.dumps({'metric': 'uptime', 'value': metric_value, 'threshold': threshold})
                )
            )
    
    if 'error_rate' in sla_rule and sla_rule['error_rate'] is not None:
        threshold = sla_rule['error_rate']['threshold']
        metric_value = metrics.get('error_rate', 0)
        if metric_value > threshold:
            breaches.append(
                BreachEvent(
                    breach_type=BreachType.ERROR_RATE, 
                    timestamp=datetime.now(timezone.utc), 
                    details=json.dumps({'metric': 'error_rate', 'value': metric_value, 'threshold': threshold})
                )
            )
    
    return breaches


@dataclass
class BreachDetector:
    session: Optional[Session] = None

    def detect_breach(self, sla_rule: SLARule, metrics: dict) -> List[BreachEvent]:
        """
        Detect breaches and optionally persist to database if session is provided.
        """
        breaches = detect_breach(sla_rule, metrics)
        
        if self.session is not None and breaches:
            for breach in breaches:
                self.session.add(breach)
            self.session.commit()
        
        return breaches


def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        temp_db_path = os.path.join(tmp_dir, 'test.db')
        engine = create_engine(f'sqlite:///{temp_db_path}', echo=False)
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        
        with SessionLocal() as session:
            # Test within SLA using standalone function
            sla_rule = {
                'latency': {'threshold': 100},
                'uptime': {'threshold': 95},
                'error_rate': {'threshold': 2}
            }
            metrics = {
                'latency': 98,
                'uptime': 96,
                'error_rate': 1.5
            }
            breaches = detect_breach(sla_rule, metrics)
            assert len(breaches) == 0, f"Expected 0 breaches, got {len(breaches)}"
            
            # Test outside SLA using detector (which persists)
            metrics = {
                'latency': 110,
                'uptime': 94,
                'error_rate': 3
            }
            detector = BreachDetector(session=session)
            breaches = detector.detect_breach(sla_rule, metrics)
            assert len(breaches) == 3, f"Expected 3 breaches, got {len(breaches)}"
            
            # Verify all breach types are present
            breach_types = {b.breach_type for b in breaches}
            assert BreachType.LATENCY in breach_types
            assert BreachType.UPTIME in breach_types
            assert BreachType.ERROR_RATE in breach_types
            
            # Verify saved to database by querying
            stmt = select(BreachEvent)
            result = session.execute(stmt)
            saved_events = result.scalars().all()
            assert len(saved_events) == 3, f"Expected 3 saved events, got {len(saved_events)}"
            
            # Verify timestamps are set and details are valid
            for event in saved_events:
                assert event.timestamp is not None
                assert isinstance(event.timestamp, datetime)
                details = json.loads(event.details)
                assert 'metric' in details
                assert 'value' in details
                assert 'threshold' in details
                
            # Verify BreachType enum is properly stored
            for event in saved_events:
                assert isinstance(event.breach_type, BreachType)
                
    logger.info("Self-test passed successfully")


if __name__ == "__main__":
    _selftest()
