"""
notification_center — In-app notification inbox model + feed.

### PART-META-JSON
{
  "name": "notification_center",
  "layer": "communication",
  "purpose": "In-app notification inbox model + feed.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: notify(db, user_id, title, body); unread(db, user_id); mark_read(db, notification_id); search_notifications(db, user_id, query, page, per_page); NotificationFeedResponse(...); Notification(...).",
  "outputs": "Returns: notify -> Notification; unread -> List[Notification]; mark_read -> Optional[Notification]; search_notifications -> NotificationFeedResponse.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `notify` from `scrapyard.communication.notification_center` and call it as shown in `example`; run `py -m scrapyard.communication.notification_center` to see its offline selftest.",
  "example": "from scrapyard.communication.notification_center import notify",
  "import_path": "scrapyard.communication.notification_center"
}
### END-PART-META
"""
from __future__ import annotations
from datetime import datetime
STATUS = "core"
from sqlalchemy import String, Integer, Text, Boolean, DateTime, func, select, and_, or_
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel
from sqlalchemy.orm import Session
from typing import List, Optional, Any

class NotificationFeedResponse:
    def __init__(self, notifications: List[Any], total_count: int):
        self.notifications = notifications
        self.total_count = total_count

class Notification(IntPKModel):
    __tablename__ = "notification_center_notifications"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

def notify(db: Session, user_id: int, title: str, body: str = "") -> Notification:
    n = Notification(user_id=user_id, title=title, body=body)
    db.add(n)
    db.flush()
    return n

def unread(db: Session, user_id: int) -> List[Notification]:
    return list(db.scalars(select(Notification).where(Notification.user_id == user_id, Notification.read == False)))

def mark_read(db: Session, notification_id: int) -> Optional[Notification]:
    n = db.get(Notification, notification_id)
    if n:
        n.read = True
        db.flush()
    return n

def search_notifications(
    db: Session,
    user_id: int,
    query: str,
    page: int = 1,
    per_page: int = 20
) -> NotificationFeedResponse:
    # Keep the search term in its own name: the previous code reassigned
    # `query` to the select() object and then interpolated THAT into the
    # count filter, so total_count never matched anything.
    term = f"%{query}%"
    criteria = and_(Notification.user_id == user_id,
                    or_(Notification.title.ilike(term), Notification.body.ilike(term)))

    stmt = select(Notification).where(criteria)
    notifications = db.scalars(stmt.offset((page - 1) * per_page).limit(per_page)).all()
    total_count = db.scalar(
        select(func.count()).select_from(Notification).where(criteria)
    ) or 0

    return NotificationFeedResponse(notifications=notifications, total_count=total_count)


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from sqlalchemy import create_engine

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                n1 = notify(db, 1, "Welcome", "Hello there")
                n2 = notify(db, 1, "Update", "Feature shipped")
                notify(db, 2, "Other user", "not yours")
                db.commit()

                assert {n.title for n in unread(db, 1)} == {"Welcome", "Update"}
                assert len(unread(db, 2)) == 1

                assert mark_read(db, n1.id).read is True
                db.commit()
                assert [n.title for n in unread(db, 1)] == ["Update"]
                assert mark_read(db, 99999) is None

                feed = search_notifications(db, 1, "feature")
                assert feed.total_count == 1
                assert feed.notifications[0].id == n2.id
                feed = search_notifications(db, 1, "nothing-matches")
                assert feed.total_count == 0 and feed.notifications == []
                # Pagination bounds
                feed = search_notifications(db, 1, "e", page=1, per_page=1)
                assert len(feed.notifications) == 1 and feed.total_count >= 1
        finally:
            engine.dispose()
    print("notification_center self-test passed")


if __name__ == "__main__":
    _selftest()
