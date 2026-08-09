"""
token_cost_logging — Log tokens + $ cost per call/user.

### PART-META-JSON
{
  "name": "token_cost_logging",
  "layer": "ai",
  "purpose": "Log tokens + $ cost per call/user.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: on_log_pre(hook); on_log_post(hook); set_pricing_rules(rules, session); log_event(model, input_tokens, output_tokens, user_id, session); log_events(events, session); CostLog(...); PricingRule(...); LogEvent(...) (plus more).",
  "outputs": "Returns: on_log_pre -> None; on_log_post -> None; set_pricing_rules -> None; log_event -> float; log_events -> List[float].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `on_log_pre` from `scrapyard.ai.token_cost_logging` and call it as shown in `example`; run `py -m scrapyard.ai.token_cost_logging` to see its offline selftest.",
  "example": "from scrapyard.ai.token_cost_logging import on_log_pre",
  "import_path": "scrapyard.ai.token_cost_logging"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
PRICES = {"claude-sonnet-4": (3.0, 15.0), "claude-opus-4": (15.0, 75.0), "default": (1.0, 3.0)}
class CostLog:
    def __init__(self): self.events = []
    def record(self, model: str, input_tokens: int, output_tokens: int) -> float:
        pin, pout = PRICES.get(model, PRICES["default"])
        cost = (input_tokens / 1_000_000) * pin + (output_tokens / 1_000_000) * pout
        self.events.append({"model": model, "in": input_tokens, "out": output_tokens, "usd": cost})
        return cost
    def total_usd(self) -> float:
        return round(sum(e["usd"] for e in self.events), 6)
    def by_model(self) -> dict:
        out = {}
        for e in self.events:
            out[e["model"]] = round(out.get(e["model"], 0) + e["usd"], 6)
        return out
log = CostLog()

import json
from sqlalchemy import func
from typing import Optional, Dict, List, Tuple, Any, Literal, Callable
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship

Base = declarative_base()


class PricingRule(Base):
    __tablename__ = 'pricing_rules'
    model_name = Column(String, primary_key=True)
    input_price = Column(Float, nullable=False)
    output_price = Column(Float, nullable=False)


class LogEvent(Base):
    __tablename__ = 'log_events'
    id = Column(Integer, primary_key=True)
    model_name = Column(String, nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey('token_cost_logging_users.id'), nullable=True)
    created_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    cost = Column(Float, nullable=False)
    user = relationship("User", back_populates="log_events")


class User(Base):
    __tablename__ = 'token_cost_logging_users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    log_events = relationship('LogEvent', back_populates='user')


# Log lifecycle hooks: registered callables invoked before/after each DB log.
_pre_hooks: List[Callable[[Dict[str, Any]], None]] = []
_post_hooks: List[Callable[[Dict[str, Any]], None]] = []


def on_log_pre(hook: Callable[[Dict[str, Any]], None]) -> None:
    """Register a hook called with the event dict before it is persisted."""
    if not callable(hook):
        raise TypeError("hook must be callable")
    _pre_hooks.append(hook)


def on_log_post(hook: Callable[[Dict[str, Any]], None]) -> None:
    """Register a hook called with the event dict (incl. cost) after commit."""
    if not callable(hook):
        raise TypeError("hook must be callable")
    _post_hooks.append(hook)


def set_pricing_rules(rules: Dict[str, Tuple[float, float]],
                      session: Session) -> None:
    """Upsert per-model (input, output) $/Mtok pricing rules."""
    for model_name, (input_price, output_price) in rules.items():
        existing = session.get(PricingRule, model_name)
        if existing is not None:
            existing.input_price = input_price
            existing.output_price = output_price
        else:
            session.add(PricingRule(model_name=model_name,
                                    input_price=input_price,
                                    output_price=output_price))
    session.commit()


def _calculate_cost(model: str, input_tokens: int, output_tokens: int,
                    session: Session) -> float:
    """Cost from DB pricing rules, falling back to the in-memory PRICES table."""
    pricing_rule = session.query(PricingRule).filter(
        PricingRule.model_name == model).first()
    if pricing_rule is not None:
        pin, pout = pricing_rule.input_price, pricing_rule.output_price
    else:
        pin, pout = PRICES.get(model, PRICES["default"])
    cost = (input_tokens / 1_000_000) * pin + (output_tokens / 1_000_000) * pout
    return round(cost, 6)


def log_event(
    model: str,
    input_tokens: int,
    output_tokens: int,
    user_id: Optional[int] = None,
    session: Optional[Session] = None,
) -> float:
    if not session:
        raise RuntimeError("Session required for DB logging")

    event_dict = {"model": model, "input_tokens": input_tokens,
                  "output_tokens": output_tokens, "user_id": user_id}
    for hook in _pre_hooks:
        try:
            hook(event_dict)
        except Exception:
            pass

    cost = _calculate_cost(model, input_tokens, output_tokens, session)
    event = LogEvent(
        model_name=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        user_id=user_id,
        cost=cost,
    )
    session.add(event)
    try:
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    event_dict["cost"] = event.cost
    for hook in _post_hooks:
        try:
            hook(event_dict)
        except Exception:
            pass
    return event.cost


def log_events(events: List[Dict[str, Any]], session: Optional[Session] = None) -> List[float]:
    if not session:
        raise RuntimeError("Session required for DB logging")
    return [log_event(e['model'], e['input_tokens'], e['output_tokens'],
                      user_id=e.get('user_id'), session=session)
            for e in events]


def get_logs(
    session: Session,
    model: Optional[str] = None,
    user_id: Optional[int] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    page: int = 1,
    per_page: int = 50,
) -> Tuple[List[Dict[str, Any]], int]:
    query = session.query(LogEvent)

    if model:
        query = query.filter(LogEvent.model_name == model)

    if user_id:
        query = query.filter(LogEvent.user_id == user_id)

    if start_time and end_time:
        query = query.filter(LogEvent.created_at >= start_time,
                             LogEvent.created_at <= end_time)

    total_count = query.count()
    logs = query.order_by(LogEvent.id).offset((page - 1) * per_page).limit(per_page).all()

    return [
        {
            "id": log.id,
            "model_name": log.model_name,
            "input_tokens": log.input_tokens,
            "output_tokens": log.output_tokens,
            "user_id": log.user_id,
            "created_at": log.created_at.isoformat(),
            "cost": log.cost,
        }
        for log in logs
    ], total_count


def aggregate_costs(
    session: Session,
    group_by: Literal["model", "user", "time"] = "model",
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Dict[str, float]:
    if group_by == "time":
        key_col = func.date(LogEvent.created_at)
    elif group_by == "user":
        key_col = LogEvent.user_id
    else:
        key_col = LogEvent.model_name

    query = session.query(key_col, func.sum(LogEvent.cost).label('total_cost'))
    if start_time and end_time:
        query = query.filter(LogEvent.created_at.between(start_time, end_time))
    if group_by == "user":
        query = query.filter(LogEvent.user_id.isnot(None))
    query = query.group_by(key_col)

    return {str(key): round(total, 6) for key, total in query.all()}


def to_json(event: Dict[str, Any]) -> str:
    return json.dumps(event)


def from_json(json_str: str) -> Dict[str, Any]:
    return json.loads(json_str)


def _selftest():
    import tempfile
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # in-memory CostLog
    cl = CostLog()
    c1 = cl.record("claude-sonnet-4", 1_000_000, 0)
    assert abs(c1 - 3.0) < 1e-9
    cl.record("unknown-model", 1_000_000, 1_000_000)
    assert abs(cl.total_usd() - (3.0 + 1.0 + 3.0)) < 1e-6
    assert "claude-sonnet-4" in cl.by_model()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'costs.db')}")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            session.add(User(username="andre"))
            session.commit()

            set_pricing_rules({"claude-sonnet-4": (3.0, 15.0),
                               "gpt-4o-mini": (0.15, 0.6)}, session)
            # upsert path
            set_pricing_rules({"claude-sonnet-4": (3.0, 15.0)}, session)

            fired = {"pre": 0, "post": 0}
            on_log_pre(lambda ev: fired.__setitem__("pre", fired["pre"] + 1))
            on_log_post(lambda ev: fired.__setitem__("post", fired["post"] + 1))

            cost = log_event("claude-sonnet-4", 2_000_000, 1_000_000,
                             user_id=1, session=session)
            assert abs(cost - (6.0 + 15.0)) < 1e-6
            assert fired == {"pre": 1, "post": 1}, "hooks must actually fire"

            # fallback pricing for unknown model (no KeyError crash)
            log_event("mystery-model", 1_000_000, 0, session=session)

            costs = log_events([
                {"model": "gpt-4o-mini", "input_tokens": 1_000_000,
                 "output_tokens": 0, "user_id": 1},
            ], session=session)
            assert abs(costs[0] - 0.15) < 1e-6

            logs, total = get_logs(session, model="claude-sonnet-4")
            assert total == 1 and logs[0]["user_id"] == 1
            assert logs[0]["created_at"]  # regression: server_default 'now()' broke inserts

            all_logs, all_total = get_logs(session, page=1, per_page=2)
            assert all_total == 3 and len(all_logs) == 2

            agg_model = aggregate_costs(session, group_by="model")
            assert "claude-sonnet-4" in agg_model and agg_model["claude-sonnet-4"] > 0
            agg_user = aggregate_costs(session, group_by="user")
            assert "1" in agg_user
            agg_time = aggregate_costs(session, group_by="time")
            assert len(agg_time) >= 1  # regression: time branch indexed user_id

            # session is now explicit everywhere
            try:
                log_event("m", 1, 1)
                raise AssertionError("expected RuntimeError without session")
            except RuntimeError:
                pass

            # json round trip
            assert from_json(to_json({"a": 1})) == {"a": 1}
        finally:
            _pre_hooks.clear()
            _post_hooks.clear()
            session.close()
            engine.dispose()

    print("token_cost_logging selftest passed")


if __name__ == "__main__":
    _selftest()
