"""
cost_accountant — Track and aggregate LLM request costs based on token usage and provider pricing. Integrates with stream_handler to capture usage metrics and apply pricing models.

### PART-META-JSON
{
  "name": "cost_accountant",
  "layer": "llm",
  "purpose": "Track and aggregate LLM request costs based on token usage and provider pricing. Integrates with stream_handler to capture usage metrics and apply pricing models.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: log_request_cost(session, model_name, prompt_tokens, completion_tokens, provider); get_total_cost(session, model_name, provider); PricingModel(...); RequestCost(...).",
  "outputs": "Returns: log_request_cost -> None; get_total_cost -> float.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.llm.cost_accountant`.",
  "example": "from scrapyard.llm.cost_accountant import *",
  "import_path": "scrapyard.llm.cost_accountant"
}
### END-PART-META
"""

from sqlalchemy import String, func, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from typing import Optional
import os
import logging
import tempfile

logger = logging.getLogger(__name__)


class PricingModel(IntPKModel):
    __tablename__ = "pricing_models"
    model_name: Mapped[str] = mapped_column(String(64), unique=True)
    prompt_rate: Mapped[float]
    completion_rate: Mapped[float]


class RequestCost(IntPKModel):
    __tablename__ = "request_costs"
    model_name: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int]
    completion_tokens: Mapped[int]
    provider: Mapped[str] = mapped_column(String(32))
    cost: Mapped[float]


def log_request_cost(session: Session, model_name: str, prompt_tokens: int, completion_tokens: int, provider: str) -> None:
    """Log the cost of an LLM request."""
    pricing = session.execute(
        select(PricingModel).where(PricingModel.model_name == model_name)
    ).scalar_one_or_none()
    
    if pricing is None:
        raise ValueError(f"No pricing model found for {model_name}")
    
    cost = (prompt_tokens * pricing.prompt_rate) + (completion_tokens * pricing.completion_rate)
    
    new_cost_entry = RequestCost(
        model_name=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        provider=provider,
        cost=cost
    )
    session.add(new_cost_entry)


def get_total_cost(session: Session, model_name: Optional[str] = None, provider: Optional[str] = None) -> float:
    """Get the total cost of requests."""
    query = select(func.sum(RequestCost.cost))
    if model_name is not None:
        query = query.where(RequestCost.model_name == model_name)
    if provider is not None:
        query = query.where(RequestCost.provider == provider)
    result = session.execute(query).scalar()
    return result or 0.0


def _selftest():
    """Self-test the module."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        IntPKModel.metadata.create_all(engine)
        
        with Session(engine) as session:
            # Setup pricing models
            prompt_rate = 0.002
            completion_rate = 0.004
            model_name = "gpt-3.5-turbo"
            pricing_model = PricingModel(
                model_name=model_name, 
                prompt_rate=prompt_rate, 
                completion_rate=completion_rate
            )
            session.add(pricing_model)
            session.commit()
            
            # Log some request costs
            log_request_cost(session, model_name, 100, 200, "provider1")
            log_request_cost(session, model_name, 50, 100, "provider2")
            
            # Calculate expected values
            cost1 = (100 * prompt_rate) + (200 * completion_rate)  # 0.2 + 0.8 = 1.0
            cost2 = (50 * prompt_rate) + (100 * completion_rate)   # 0.1 + 0.4 = 0.5
            expected_total = cost1 + cost2  # 1.5
            
            # Test get_total_cost for all requests
            total_cost = get_total_cost(session)
            assert round(total_cost, 4) == round(expected_total, 4), f"Expected {expected_total}, got {total_cost}"
            
            # Test get_total_cost filtered by model
            total_cost_model = get_total_cost(session, model_name=model_name)
            assert round(total_cost_model, 4) == round(expected_total, 4), f"Expected {expected_total}, got {total_cost_model}"
            
            # Test get_total_cost filtered by provider
            total_cost_provider1 = get_total_cost(session, provider="provider1")
            assert round(total_cost_provider1, 4) == round(cost1, 4), f"Expected {cost1}, got {total_cost_provider1}"
            
            total_cost_provider2 = get_total_cost(session, provider="provider2")
            assert round(total_cost_provider2, 4) == round(cost2, 4), f"Expected {cost2}, got {total_cost_provider2}"
            
            # Test non-existent filter returns 0.0
            total_cost_nonexistent = get_total_cost(session, provider="nonexistent")
            assert total_cost_nonexistent == 0.0, f"Expected 0.0, got {total_cost_nonexistent}"
            
            # Verify entries were created (via autoflush on query)
            entries = session.execute(select(RequestCost)).scalars().all()
            assert len(entries) == 2
            assert entries[0].provider == "provider1"
            assert entries[1].provider == "provider2"
            assert entries[0].cost == cost1
            assert entries[1].cost == cost2
            
            session.rollback()
        
        engine.dispose()


if __name__ == "__main__":
    _selftest()
