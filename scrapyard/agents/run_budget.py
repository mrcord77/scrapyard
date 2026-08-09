"""
run_budget — ** The `scrapyard.agents.run_budget` module manages resource budgets for agent runs, enforcing limits and terminating execution when thresholds are exceeded. It ensures efficient use of computational 

### PART-META-JSON
{
  "name": "run_budget",
  "layer": "agents",
  "purpose": "Manages resource budgets for agent runs, enforcing limits and terminating execution when thresholds are exceeded. It ensures efficient use of computational.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: start_run(budget); RunBudget(...); ResourceUsage(...); BudgetManager(...).",
  "outputs": "Returns: start_run -> RunBudget.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.run_budget`.",
  "example": "from scrapyard.agents.run_budget import *",
  "import_path": "scrapyard.agents.run_budget"
}
### END-PART-META
"""
from sqlalchemy import String, Integer, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

_run_id_counter = 0

def _get_next_run_id() -> int:
    global _run_id_counter
    _run_id_counter += 1
    return _run_id_counter


@dataclass
class RunBudget:
    id: int
    budget: Optional[int] = None
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    resource_usage: List[Dict[str, Any]] = field(default_factory=list)


class ResourceUsage(IntPKModel):
    __tablename__ = 'run_budget_resource_usage'
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(50))
    amount: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[int] = mapped_column(Integer)


def start_run(budget: Optional[int] = None) -> RunBudget:
    run_id = _get_next_run_id()
    run_budget = RunBudget(id=run_id, budget=budget)
    return run_budget


class BudgetManager:
    def __init__(self, session: Optional[Session] = None):
        self.run_budgets = {}
        self.session = session
    
    def consume_resource(self, resource: str, amount: int, run_id: int) -> None:
        if run_id not in self.run_budgets:
            raise ValueError("Run ID does not exist")
        
        current_budget = self.run_budgets[run_id].budget
        if current_budget is not None and amount > current_budget:
            raise ValueError(f"Exceeded budget for run {run_id}")
        
        usage_entry = {
            'type': resource,
            'amount': amount,
            'timestamp': datetime.now(timezone.utc)
        }
        self.run_budgets[run_id].resource_usage.append(usage_entry)
        
        if self.session:
            usage_record = ResourceUsage(type=resource, amount=amount, run_id=run_id)
            self.session.add(usage_record)
            self.session.commit()


def _selftest():
    # Setup
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        ResourceUsage.metadata.create_all(engine)
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        try:
            budget_manager = BudgetManager(session=session)
            
            # Test 1: Initialize a run with a budget and consume resources within the limit
            run_id_1 = start_run(budget=50)
            budget_manager.run_budgets[run_id_1.id] = RunBudget(id=run_id_1.id, budget=50)
            try:
                budget_manager.consume_resource('CPU', 30, run_id_1.id)
                assert len(budget_manager.run_budgets[run_id_1.id].resource_usage) == 1
            except ValueError as e:
                logger.error(e)
                raise
            
            # Verify database state
            stmt = select(ResourceUsage).where(ResourceUsage.run_id == run_id_1.id)
            db_records = list(session.scalars(stmt))
            assert len(db_records) == 1
            assert db_records[0].type == 'CPU'
            assert db_records[0].amount == 30
            
            # Test 2: Attempt to consume more resources than the budget allows
            try:
                budget_manager.consume_resource('CPU', 60, run_id_1.id)
                assert False, "Expected a ValueError for exceeding budget"
            except ValueError as e:
                assert str(e) == f"Exceeded budget for run {run_id_1.id}"
            
            # Verify no additional record was created for failed consumption
            db_records_after_fail = list(session.scalars(stmt))
            assert len(db_records_after_fail) == 1
            
            # Test 3: Initialize a run without a budget and consume resources
            run_id_2 = start_run()
            budget_manager.run_budgets[run_id_2.id] = RunBudget(id=run_id_2.id)
            try:
                budget_manager.consume_resource('Memory', 40, run_id_2.id)
                assert len(budget_manager.run_budgets[run_id_2.id].resource_usage) == 1
            except ValueError as e:
                logger.error(e)
                raise
            
            # Verify database state for second run
            stmt2 = select(ResourceUsage).where(ResourceUsage.run_id == run_id_2.id)
            db_records_2 = list(session.scalars(stmt2))
            assert len(db_records_2) == 1
            assert db_records_2[0].type == 'Memory'
            assert db_records_2[0].amount == 40
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
