"""
usage_metering — Record metered usage for usage-based billing.

### PART-META-JSON
{
  "name": "usage_metering",
  "layer": "billing",
  "purpose": "Record metered usage for usage-based billing.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: record_usage(db, user_id, metric, quantity); total_usage(db, user_id, metric); within_quota(db, user_id, metric, quota); record_usage_bulk(db, events); list_usage_events(db, user_id, metric, start, end, limit, offset); UsageEvent(...) (plus more).",
  "outputs": "Returns: record_usage -> UsageEvent; total_usage -> int; within_quota -> bool; record_usage_bulk -> List[UsageEvent]; list_usage_events -> List[UsageEvent].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `record_usage` from `scrapyard.billing.usage_metering` and call it as shown in `example`; run `py -m scrapyard.billing.usage_metering` to see its offline selftest.",
  "example": "from scrapyard.billing.usage_metering import record_usage",
  "import_path": "scrapyard.billing.usage_metering"
}
### END-PART-META
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from typing import List, Optional, Dict, Union
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from scrapyard.database.base_model import IntPKModel

STATUS = "core"

class UsageEvent(IntPKModel):
    __tablename__ = "usage_events"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    metric: Mapped[str] = mapped_column(String(50), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived: Mapped[bool] = mapped_column(default=False)

def record_usage(db: Session, user_id: int, metric: str, quantity: int = 1) -> UsageEvent:
    ev = UsageEvent(user_id=user_id, metric=metric, quantity=quantity)
    db.add(ev)
    db.flush()
    return ev

def total_usage(db: Session, user_id: int, metric: str) -> int:
    result = db.scalar(
        select(func.coalesce(func.sum(UsageEvent.quantity), 0))
        .where(UsageEvent.user_id == user_id, UsageEvent.metric == metric)
    )
    return result or 0

def within_quota(db: Session, user_id: int, metric: str, quota: int) -> bool:
    return quota < 0 or total_usage(db, user_id, metric) < quota

def record_usage_bulk(db: Session, events: List[UsageEvent]) -> List[UsageEvent]:
    try:
        db.add_all(events)
        db.commit()
    except IntegrityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return events

def list_usage_events(
    db: Session,
    user_id: Optional[int] = None,
    metric: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0
) -> List[UsageEvent]:
    query = db.query(UsageEvent)
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    if metric is not None:
        query = query.filter_by(metric=metric)
    if start is not None:
        query = query.filter(UsageEvent.at >= start)
    if end is not None:
        query = query.filter(UsageEvent.at <= end)
    return query.offset(offset).limit(limit).all()

def get_usage_history(
    db: Session,
    user_id: int,
    metric: str,
    start: datetime,
    end: datetime
) -> List[UsageEvent]:
    return db.query(UsageEvent).filter_by(user_id=user_id, metric=metric).filter(UsageEvent.at.between(start, end)).all()

def archive_usage_events(db: Session, event_ids: List[int]) -> List[int]:
    archived_events = []
    for event_id in event_ids:
        try:
            event = db.query(UsageEvent).filter_by(id=event_id).first()
            if event:
                event.archived = True
                db.commit()
                archived_events.append(event_id)
        except IntegrityError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return archived_events

def update_usage_event(
    db: Session,
    event_id: int,
    quantity: Optional[int] = None,
    metric: Optional[str] = None
) -> UsageEvent:
    event = db.query(UsageEvent).filter_by(id=event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Usage event not found")
    if quantity is not None:
        event.quantity = quantity
    if metric is not None:
        event.metric = metric
    try:
        db.commit()
    except IntegrityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return event

def calculate_usage_trend(
    db: Session,
    user_id: int,
    metric: str,
    period: str = "daily",
    start: Optional[datetime] = None,
    end: Optional[datetime] = None
) -> Dict[str, int]:
    query = db.query(UsageEvent)
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    if metric is not None:
        query = query.filter_by(metric=metric)
    if start is not None and end is not None:
        query = query.filter(UsageEvent.at.between(start, end))
    
    trends = {"daily": {}, "weekly": {}, "monthly": {}}
    for event in query.all():
        if period == "daily":
            key = event.at.strftime("%Y-%m-%d")
        elif period == "weekly":
            key = event.at.strftime("%Y-%W")
        elif period == "monthly":
            key = event.at.strftime("%Y-%m")
        else:
            continue
        trends[period][key] = trends[period].get(key, 0) + event.quantity
    
    return {k: v for k, v in trends.items() if v}

def apply_usage_policy(
    db: Session,
    user_id: int,
    metric: str,
    policy: Dict[str, Union[int, str]]
) -> Dict:
    current_usage = total_usage(db, user_id, metric)
    result = {"status": "ok", "current_usage": current_usage}
    if "threshold" in policy and current_usage >= policy["threshold"]:
        result["status"] = "exceeded"
    elif "rate_limit" in policy:
        # Placeholder for rate limit logic
        pass
    return result

def serialize_usage_event(event: UsageEvent) -> Dict:
    # Copy: never mutate the live ORM instance's __dict__.
    return {k: v for k, v in event.__dict__.items() if not k.startswith("_")}

def audit_usage_event(event: UsageEvent, user: str, action: str) -> None:
    """Emit a structured audit log line for a usage-event mutation."""
    import logging
    logging.getLogger(__name__).info(
        "usage_audit action=%s user=%s event_id=%s metric=%s quantity=%s",
        action, user, event.id, event.metric, event.quantity,
    )

def _selftest() -> None:
    import tempfile, os
    from datetime import timedelta, timezone
    from sqlalchemy import create_engine

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                record_usage(db, 1, "api_calls", 5)
                record_usage(db, 1, "api_calls", 3)
                record_usage(db, 2, "api_calls", 7)
                record_usage(db, 1, "storage_mb", 100)
                db.commit()

                assert total_usage(db, 1, "api_calls") == 8
                assert total_usage(db, 1, "missing") == 0
                assert within_quota(db, 1, "api_calls", 10) is True
                assert within_quota(db, 1, "api_calls", 8) is False
                assert within_quota(db, 1, "api_calls", -1) is True  # unlimited

                events = list_usage_events(db, user_id=1, metric="api_calls")
                assert len(events) == 2
                all_for_user = list_usage_events(db, user_id=1)
                assert len(all_for_user) == 3

                # bulk insert
                record_usage_bulk(db, [UsageEvent(user_id=3, metric="api_calls", quantity=2)])
                assert total_usage(db, 3, "api_calls") == 2

                # history window
                now = datetime.now(timezone.utc)
                hist = get_usage_history(db, 1, "api_calls",
                                         now - timedelta(days=1), now + timedelta(days=1))
                assert len(hist) == 2

                # update + archive
                ev = events[0]
                update_usage_event(db, ev.id, quantity=9)
                assert db.get(UsageEvent, ev.id).quantity == 9
                try:
                    update_usage_event(db, 999999)
                    assert False
                except HTTPException as e:
                    assert e.status_code == 404
                archived = archive_usage_events(db, [ev.id, 999999])
                assert archived == [ev.id]
                assert db.get(UsageEvent, ev.id).archived is True

                # serialization copies (live instance keeps its state)
                data = serialize_usage_event(ev)
                assert "_sa_instance_state" not in data and data["id"] == ev.id
                assert "_sa_instance_state" in ev.__dict__

                # trend + policy
                trend = calculate_usage_trend(db, 1, "api_calls", period="daily")
                assert sum(trend["daily"].values()) == total_usage(db, 1, "api_calls")
                policy = apply_usage_policy(db, 1, "api_calls", {"threshold": 5})
                assert policy["status"] == "exceeded"
                assert apply_usage_policy(db, 1, "api_calls", {"threshold": 10**6})["status"] == "ok"

                audit_usage_event(ev, "tester", "archive")  # must not raise
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("usage_metering selftest OK")
