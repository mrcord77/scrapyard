"""
access_review_scheduler — Schedule periodic user-access reviews and trigger them on demand.

### PART-META-JSON
{
  "name": "access_review_scheduler",
  "layer": "audit_governance",
  "purpose": "Schedule periodic user-access reviews and trigger them on demand: AccessReview and ReviewSchedule ORM rows track per-user review status and next-run times for 'daily' or monthly intervals; schedule_review() creates the pair, trigger_review() flips a review to 'triggered' with a fresh timestamp.",
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "schedule_review(user_id, interval) with interval 'daily' (next run +1 day) or anything else treated as monthly (+30 days); trigger_review(review_id). The module-level Session factory must be bound to an engine (reassign `Session = sessionmaker(bind=engine)`) before use.",
  "outputs": "schedule_review returns the new AccessReview id; trigger_review returns None and raises ValueError for unknown ids; rows persisted in access_review / review_schedule tables.",
  "files_created": [],
  "security_notes": "No authentication or authorization layer: any caller can schedule or trigger a review for any user_id, so gate these functions behind an admin permission check in the composing app. user_id is a plain integer column (no FK) - referential integrity against your user table is the composing app's responsibility. No secrets or PII beyond user ids are handled; scheduling is passive (rows only) - actually running reviews is the caller's job.",
  "ai_usage": "Bind Session to your engine, create tables via IntPKModel.metadata, then rid = schedule_review(user_id, 'daily'); later trigger_review(rid).",
  "example": "from scrapyard.audit_governance.access_review_scheduler import schedule_review, trigger_review",
  "import_path": "scrapyard.audit_governance.access_review_scheduler"
}
### END-PART-META
"""
from sqlalchemy import String, DateTime, select, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session as _Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from typing import Callable, Any, Optional
import logging, tempfile

logger = logging.getLogger(__name__)

# Session factory; reassign to a sessionmaker bound to your engine before use.
Session: Callable[..., Any] = _Session


class AccessReview(IntPKModel):
    __tablename__ = 'access_review'

    user_id: Mapped[int] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(50))
    last_run: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    next_run: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ReviewSchedule(IntPKModel):
    __tablename__ = 'review_schedule'

    review_id: Mapped[int] = mapped_column(ForeignKey('access_review.id'), index=True)
    interval: Mapped[str] = mapped_column(String(50))
    next_trigger: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def schedule_review(user_id: int, interval: str) -> int:
    """Create an AccessReview + ReviewSchedule pair; returns the review id."""
    now = datetime.now(timezone.utc)
    if interval == 'daily':
        next_run = now + timedelta(days=1)
    else:  # treated as monthly
        next_run = (now.replace(hour=0, minute=0, second=0, microsecond=0)
                    + timedelta(days=30))

    with Session() as session:
        review = AccessReview(user_id=user_id, status='scheduled', next_run=next_run)
        session.add(review)
        session.flush()  # assign review.id
        schedule = ReviewSchedule(review_id=review.id, interval=interval,
                                  next_trigger=next_run)
        session.add(schedule)
        session.commit()
        return review.id


def trigger_review(review_id: int) -> None:
    """Mark the review as triggered now; raises ValueError for unknown ids."""
    with Session() as session:
        review = session.get(AccessReview, review_id)

        if not review:
            raise ValueError(f"No access review found for id {review_id}")

        review.status = 'triggered'
        review.next_run = datetime.now(timezone.utc)
        session.commit()


def _selftest() -> None:
    """Offline self-test against a temporary SQLite database. Raises on failure."""
    global Session
    previous_session = Session
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        from sqlalchemy import create_engine
        engine = create_engine(f'sqlite:///{temp_dir}/test.db')
        try:
            # Only this part's tables (the user table FK is not exercised here).
            AccessReview.__table__.create(engine)
            ReviewSchedule.__table__.create(engine)
            Session = sessionmaker(bind=engine)

            review_id = schedule_review(user_id=1, interval='daily')
            assert isinstance(review_id, int)

            with Session() as session:
                sched = session.execute(
                    select(ReviewSchedule).where(ReviewSchedule.review_id == review_id)
                ).scalars().one()
                assert sched.interval == 'daily'

            trigger_review(review_id)

            with Session() as session:
                result = session.execute(
                    select(AccessReview).where(AccessReview.id == review_id)
                ).scalars().one()
                assert result.status == 'triggered'
                assert result.next_run is not None

            # Unknown review id must raise.
            try:
                trigger_review(99999)
                raise AssertionError("expected ValueError for unknown review id")
            except ValueError:
                pass

            logger.info("Self-test passed successfully.")
        finally:
            Session = previous_session
            engine.dispose()


if __name__ == "__main__":
    _selftest()
