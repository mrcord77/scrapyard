"""
usage_metrics — Aggregate active users / feature usage.

### PART-META-JSON
{
  "name": "usage_metrics",
  "layer": "analytics",
  "purpose": "Aggregate active users / feature usage.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: track_user_activity(db, user_id, feature_name, metadata); get_feature_usage(db, start, end, user_id, page, per_page); archive_old_events(db, older_than); bulk_track_user_activities(db, activities); get_active_users_with_filters(db, filters, page, per_page); EventMetadata(...); FeatureUsageResponse(...); UserActivity(...) (plus more).",
  "outputs": "Returns: track_user_activity -> None; get_feature_usage -> Dict[str, FeatureUsageResponse]; archive_old_events -> int; bulk_track_user_activities -> None; get_active_users_with_filters -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `track_user_activity` from `scrapyard.analytics.usage_metrics` and call it as shown in `example`; run `py -m scrapyard.analytics.usage_metrics` to see its offline selftest.",
  "example": "from scrapyard.analytics.usage_metrics import track_user_activity",
  "import_path": "scrapyard.analytics.usage_metrics"
}
### END-PART-META
"""
from __future__ import annotations
from typing import List, Dict, Any, Callable, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from pydantic import BaseModel
from sqlalchemy import func, select
from scrapyard.analytics.event_tracking import AnalyticsEvent

STATUS = "core"
_METRIC_HOOKS: List[Callable[[Dict[str, Any]], None]] = []

class EventMetadata(BaseModel):
    metadata: Optional[Dict[str, Any]] = None

class FeatureUsageResponse(BaseModel):
    feature_name: str
    count: int

class UserActivity(BaseModel):
    user_id: int
    feature_name: str
    metadata: Optional[Dict[str, Any]] = None

def track_user_activity(db: Session, user_id: int, feature_name: str, metadata: EventMetadata = None) -> None:
    """Record a feature usage event on the canonical AnalyticsEvent model.

    feature_name maps to AnalyticsEvent.name; metadata is stored as JSON props.
    """
    import json as _json
    props = metadata.metadata if (metadata and metadata.metadata) else {}
    event = AnalyticsEvent(user_id=user_id, name=feature_name, props=_json.dumps(props))
    db.add(event)
    db.commit()
    payload = {"user_id": user_id, "feature_name": feature_name, "metadata": props}
    for hook in tuple(_METRIC_HOOKS):
        hook(payload)

def get_feature_usage(
    db: Session,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    user_id: Optional[int] = None,
    page: int = 1,
    per_page: int = 50
) -> Dict[str, FeatureUsageResponse]:
    query = select(AnalyticsEvent.name, func.count()).group_by(AnalyticsEvent.name)

    if start is not None:
        query = query.where(AnalyticsEvent.at >= start)
    if end is not None:
        query = query.where(AnalyticsEvent.at <= end)
    if user_id is not None:
        query = query.where(AnalyticsEvent.user_id == user_id)

    results = db.execute(query).all()

    return {r[0]: FeatureUsageResponse(feature_name=r[0], count=r[1]) for r in results}

def archive_old_events(db: Session, older_than: datetime) -> int:
    deleted_count = db.query(AnalyticsEvent).filter(AnalyticsEvent.at < older_than).delete(synchronize_session=False)
    db.commit()
    return deleted_count

def bulk_track_user_activities(db: Session, activities: List[UserActivity]) -> None:
    if not activities:
        raise ValueError("Activities list cannot be empty")
    
    for activity in activities:
        track_user_activity(db, activity.user_id, activity.feature_name,
                            metadata=EventMetadata(metadata=activity.metadata) if activity.metadata else None)
    db.commit()

def get_active_users_with_filters(
    db: Session,
    filters: Optional[Dict[str, Any]] = None,
    page: int = 1,
    per_page: int = 50
) -> Dict[str, Any]:
    query = select(AnalyticsEvent.user_id).distinct()
    
    if filters:
        for key, value in filters.items():
            query = query.where(getattr(AnalyticsEvent, key) == value)
    
    total_count = db.execute(query.with_only_columns(func.count(func.distinct(AnalyticsEvent.user_id))).order_by(None)).scalar()
    paginated_users = db.execute(
        query.order_by(AnalyticsEvent.user_id).offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()

    return {"total": total_count, "users": [user_id for user_id in paginated_users]}

def configure_serializer(serializer_type: str = "json") -> None:
    if serializer_type not in ["json", "csv"]:
        raise ValueError("Invalid serializer type. Choose 'json' or 'csv'.")
    # Configuration logic here

def register_metric_hook(hook_func: Callable[[Dict[str, Any]], None]) -> None:
    if not callable(hook_func):
        raise TypeError("metric hook must be callable")
    if hook_func not in _METRIC_HOOKS:
        _METRIC_HOOKS.append(hook_func)

def get_user_feature_history(
    db: Session,
    user_id: int,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    query = select(AnalyticsEvent).where(AnalyticsEvent.user_id == user_id)
    
    if start is not None:
        query = query.where(AnalyticsEvent.at >= start)
    if end is not None:
        query = query.where(AnalyticsEvent.at <= end)

    results = db.execute(query).scalars().all()
    return [
        {k: v for k, v in event.__dict__.items() if not k.startswith("_")}
        for event in results
    ]


# --- grafted from original part (API stability) ---
def active_users(db, since=None):
    from scrapyard.analytics.event_tracking import AnalyticsEvent
    q=select(func.count(func.distinct(AnalyticsEvent.user_id)))
    if since is not None: q=q.where(AnalyticsEvent.at>=since)
    return db.scalar(q) or 0

def events_by_name(db):
    from scrapyard.analytics.event_tracking import AnalyticsEvent
    rows=db.execute(select(AnalyticsEvent.name, func.count()).group_by(AnalyticsEvent.name)).all()
    return {r[0]:r[1] for r in rows}


def _selftest() -> None:
    import tempfile, os, json as _json
    from datetime import timedelta, timezone
    from sqlalchemy import create_engine
    from scrapyard.database.base_model import IntPKModel

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                observed = []
                register_metric_hook(observed.append)
                track_user_activity(db, 1, "editor", EventMetadata(metadata={"doc": 7}))
                assert observed[-1] == {"user_id": 1, "feature_name": "editor",
                                        "metadata": {"doc": 7}}
                track_user_activity(db, 1, "editor")
                track_user_activity(db, 2, "export")
                bulk_track_user_activities(db, [
                    UserActivity(user_id=3, feature_name="editor", metadata={"doc": 9}),
                    UserActivity(user_id=3, feature_name="share"),
                ])
                try:
                    bulk_track_user_activities(db, [])
                    assert False
                except ValueError:
                    pass

                usage = get_feature_usage(db)
                assert usage["editor"].count == 3
                assert usage["export"].count == 1

                only_u1 = get_feature_usage(db, user_id=1)
                assert only_u1["editor"].count == 2 and "export" not in only_u1

                active = get_active_users_with_filters(db)
                assert active["total"] == 3 and set(active["users"]) == {1, 2, 3}

                hist = get_user_feature_history(db, 3)
                assert len(hist) == 2
                assert all(not k.startswith("_") for h in hist for k in h)
                assert _json.loads([h for h in hist if h["name"] == "editor"][0]["props"]) == {"doc": 9}

                assert active_users(db) == 3
                assert events_by_name(db)["editor"] == 3

                # archive removes old events
                future = datetime.now(timezone.utc) + timedelta(days=1)
                removed = archive_old_events(db, future)
                assert removed == 5
                assert active_users(db) == 0

                try:
                    configure_serializer("xml")
                    assert False
                except ValueError:
                    pass
                configure_serializer("json")
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("usage_metrics selftest OK")

