"""
event_tracking — Capture typed product events.

### PART-META-JSON
{
  "name": "event_tracking",
  "layer": "analytics",
  "purpose": "Capture typed product events.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: track_event(db, name, user_id, props, **kwargs); get_events(db, name, user_id, limit, offset); update_event_props(db, event_id, props); archive_event(db, event_id); bulk_track_events(db, events); EventHook(...); PolicyRegistry(...); AnalyticsEvent(...) (plus more).",
  "outputs": "Returns: track_event -> AnalyticsEvent; get_events -> List[AnalyticsEvent]; update_event_props -> None; archive_event -> None; bulk_track_events -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `track_event` from `scrapyard.analytics.event_tracking` and call it as shown in `example`; run `py -m scrapyard.analytics.event_tracking` to see its offline selftest.",
  "example": "from scrapyard.analytics.event_tracking import track_event",
  "import_path": "scrapyard.analytics.event_tracking"
}
### END-PART-META
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, TypeVar, Union
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, func, select, and_, or_
from sqlalchemy.orm import Mapped, mapped_column, Session as SessionType
from sqlalchemy.exc import IntegrityError
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError, validator
from scrapyard.database.base_model import IntPKModel
import json
import logging

STATUS = "core"

class EventHook(BaseModel):
    hook_name: str
    hook_func: Any

class PolicyRegistry:
    def __init__(self):
        self.policies = {}

    def should_log(self, key: str) -> bool:
        return self.policies.get(key, True)

    def set_policy(self, policy: str, value: Any):
        self.policies[policy] = value

registry = PolicyRegistry()

T = TypeVar('T', bound='AnalyticsEvent')

class AnalyticsEvent(IntPKModel):
    __tablename__ = "analytics_events"
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    props: Mapped[str] = mapped_column(Text, default="{}")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

def track_event(db: SessionType, name: str, user_id: Optional[int] = None, props: Dict[str, Any] = {}, **kwargs) -> AnalyticsEvent:
    clean_props = {k: v for k, v in props.items() if registry.should_log(k)}
    event = AnalyticsEvent(name=name, user_id=user_id, props=json.dumps(clean_props), **kwargs)
    db.add(event)
    try:
        db.flush()
    except IntegrityError as e:
        raise ValueError(f"Failed to track event: {e}")
    return event

def get_events(db: SessionType, name: Optional[str] = None, user_id: Optional[int] = None, limit: int = 10, offset: int = 0) -> List[AnalyticsEvent]:
    query = select(AnalyticsEvent).where(
        and_(
            AnalyticsEvent.name == name if name else True,
            AnalyticsEvent.user_id == user_id if user_id else True
        )
    )
    return db.scalars(query.limit(limit).offset(offset)).all()

def update_event_props(db: SessionType, event_id: int, props: Dict[str, Any]) -> None:
    clean_props = {k: v for k, v in props.items() if registry.should_log(k)}
    db.query(AnalyticsEvent).filter_by(id=event_id).update({"props": json.dumps(clean_props)})
    try:
        db.commit()
    except IntegrityError as e:
        raise ValueError(f"Failed to update event properties: {e}")

def archive_event(db: SessionType, event_id: int) -> None:
    db.query(AnalyticsEvent).filter_by(id=event_id).update({"archived_at": func.now()})
    try:
        db.commit()
    except IntegrityError as e:
        raise ValueError(f"Failed to archive event: {e}")

def bulk_track_events(db: SessionType, events: List[Dict[str, Any]]) -> None:
    for event_data in events:
        clean_props = {k: v for k, v in event_data.get("props", {}).items() if registry.should_log(k)}
        db.add(AnalyticsEvent(name=event_data["name"], user_id=event_data.get("user_id"), props=json.dumps(clean_props)))
    try:
        db.flush()
    except IntegrityError as e:
        raise ValueError(f"Failed to bulk track events: {e}")

def get_event_by_id(db: SessionType, event_id: int) -> Optional[AnalyticsEvent]:
    return db.query(AnalyticsEvent).filter_by(id=event_id).first()

def search_events(db: SessionType, query: str, limit: int = 10, offset: int = 0) -> List[AnalyticsEvent]:
    """Substring search over event props/name (portable: plain LIKE, parameterized)."""
    terms = [t for t in query.split() if t]
    if not terms:
        return []
    filters = [
        or_(AnalyticsEvent.props.like(f"%{term}%"), AnalyticsEvent.name.like(f"%{term}%"))
        for term in terms
    ]
    stmt = select(AnalyticsEvent).where(or_(*filters))
    return db.scalars(stmt.limit(limit).offset(offset)).all()

def serialize_event(event: AnalyticsEvent, include_props: bool = True) -> Dict[str, Any]:
    # Copy: never mutate the live ORM instance's __dict__.
    event_dict = {k: v for k, v in event.__dict__.items() if not k.startswith("_")}
    if not include_props:
        event_dict.pop("props", None)
    return jsonable_encoder(event_dict)

event_serializer = lambda include_props=True: lambda event: serialize_event(event, include_props=include_props)

# In-process hook registry. Hooks are Python callables and cannot be meaningfully
# persisted to the database (the old implementation interpolated them into raw
# SQL against a nonexistent table - an injection-shaped bug, now removed).
_EVENT_HOOKS: Dict[str, Any] = {}

def register_event_hook(hook_name: str, hook_func: Any) -> None:
    if not callable(hook_func):
        raise ValueError("hook_func must be callable")
    _EVENT_HOOKS[hook_name] = EventHook(hook_name=hook_name, hook_func=hook_func)

def unregister_event_hook(hook_name: str) -> None:
    _EVENT_HOOKS.pop(hook_name, None)

def apply_event_hooks(event: AnalyticsEvent, db: SessionType) -> None:
    for hook in list(_EVENT_HOOKS.values()):
        try:
            hook.hook_func(event)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Failed to apply event hook %s: %s", hook.hook_name, e)

def event_policy_config(policy: str, value: Any) -> None:
    registry.set_policy(policy, value)

def get_event_count(db: SessionType, name: Optional[str] = None, user_id: Optional[int] = None) -> int:
    query = select(func.count()).select_from(AnalyticsEvent).where(
        and_(
            AnalyticsEvent.name == name if name else True,
            AnalyticsEvent.user_id == user_id if user_id else True
        )
    )
    return db.scalar(query) or 0

def get_event_stats(db: SessionType) -> Dict[str, Any]:
    stats = {
        "total_events": db.query(func.count()).select_from(AnalyticsEvent).scalar() or 0,
        "unique_users": db.query(func.distinct(AnalyticsEvent.user_id)).count(),
        "event_types": db.query(AnalyticsEvent.name).distinct().count()
    }
    return stats


# --- grafted from original part (API stability) ---
import json as _json

def track(db, name, user_id=None, **props):
    from scrapyard.compliance.privacy_policy_hooks import registry
    clean={k:v for k,v in props.items() if registry.should_log(k)}
    e=AnalyticsEvent(name=name, user_id=user_id, props=_json.dumps(clean))
    db.add(e); db.flush(); return e

def count_events(db, name):
    return db.scalar(select(func.count()).select_from(AnalyticsEvent).where(AnalyticsEvent.name==name)) or 0


def _selftest() -> None:
    import tempfile, os
    from sqlalchemy import create_engine

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with SessionType(engine) as db:
                e1 = track_event(db, "signup", user_id=1, props={"plan": "pro"})
                e2 = track_event(db, "login", user_id=1)
                track_event(db, "login", user_id=2)
                db.commit()

                assert get_event_count(db, name="login") == 2
                assert count_events(db, "signup") == 1
                assert get_event_by_id(db, e1.id).name == "signup"
                assert len(get_events(db, name="login")) == 2
                assert len(get_events(db, user_id=1)) == 2

                # search is portable substring match, parameterized
                found = search_events(db, "pro")
                assert any(ev.id == e1.id for ev in found)
                assert search_events(db, "") == []

                # serialize copies - the live instance keeps its props
                data = serialize_event(e1, include_props=False)
                assert "props" not in data and "name" in data
                assert e1.props is not None

                # policy registry filters props
                event_policy_config("ssn", False)
                e4 = track_event(db, "kyc", user_id=3, props={"ssn": "123", "ok": 1})
                assert "ssn" not in json.loads(e4.props) and "ok" in json.loads(e4.props)
                registry.set_policy("ssn", True)

                # hooks: in-process registry, exceptions contained
                seen = []
                register_event_hook("collect", lambda ev: seen.append(ev.name))
                register_event_hook("boom", lambda ev: (_ for _ in ()).throw(RuntimeError()))
                try:
                    apply_event_hooks(e1, db)
                finally:
                    unregister_event_hook("collect")
                    unregister_event_hook("boom")
                assert seen == ["signup"]
                try:
                    register_event_hook("bad", "not callable")
                    assert False
                except ValueError:
                    pass

                # update/archive
                update_event_props(db, e2.id, {"ip": "1.2.3.4"})
                assert json.loads(get_event_by_id(db, e2.id).props)["ip"] == "1.2.3.4"
                archive_event(db, e2.id)
                assert get_event_by_id(db, e2.id).archived_at is not None

                # bulk + stats + grafted track()
                bulk_track_events(db, [{"name": "b1"}, {"name": "b2", "user_id": 9}])
                track(db, "grafted", user_id=9, note="x")
                db.commit()
                stats = get_event_stats(db)
                assert stats["total_events"] == 7
                assert stats["event_types"] >= 5
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("event_tracking selftest OK")

