"""
no_show_tracker — Record appointment no-shows and compute per-resource no-show rates.

### PART-META-JSON
{
  "name": "no_show_tracker",
  "layer": "scheduling",
  "purpose": "Track scheduling no-shows: mark_no_show(slot_id, user_id) persists a NoShow row against the canonical Slot model (owned by scheduling/slot_manager, imported rather than duplicated), and get_no_show_rate(resource_id) returns no_show_count / total_slots for that resource (0.0 when the resource has no slots). A NoShowTracker class mirrors the module-level functions for callers preferring an object API.",
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Module-level Session must be rebound to a sessionmaker(bind=engine) before use; mark_no_show(slot_id, user_id); get_no_show_rate(resource_id).",
  "outputs": "NoShow rows (no_shows table, FK to slot_manager_slots.id); float no-show rates in [0, 1].",
  "files_created": [],
  "security_notes": "No validation that slot_id exists or that user_id was actually booked on that slot - a caller can fabricate no-show records, and repeated marks for the same slot/user are not deduplicated, inflating rates; enforce booking checks and idempotency in the composing app. No-show history is behavioral PII about identifiable users: apply retention limits and access control upstream. No authentication here.",
  "ai_usage": "Bind Session to your engine (tables via IntPKModel.metadata.create_all), then mark_no_show(slot.id, user.id); rate = get_no_show_rate(resource_id).",
  "example": "from scrapyard.scheduling.no_show_tracker import mark_no_show, get_no_show_rate",
  "import_path": "scrapyard.scheduling.no_show_tracker"
}
### END-PART-META
"""

from sqlalchemy import create_engine, func, ForeignKey, Index, select
from sqlalchemy.orm import Mapped, mapped_column, Session as _Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Callable, Any
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

# Imported session factory/callable from the project session layer.
# Reassignable for offline testing; functions resolve this name at runtime.
Session: Callable[..., Any] = _Session


# Canonical-owner pattern: slot_manager owns the Slot model for the
# scheduling layer; this part imports it instead of declaring a duplicate.
from scrapyard.scheduling.slot_manager import Slot


class NoShow(IntPKModel):
    """A single no-show record for a scheduled slot and user."""
    __tablename__ = "no_shows"
    slot_id: Mapped[int] = mapped_column(ForeignKey("slot_manager_slots.id"), index=True)
    user_id: Mapped[int] = mapped_column(index=True)
    timestamp: Mapped[datetime] = mapped_column(default=datetime.now(timezone.utc))


Index("ix_no_shows_slot_user", NoShow.slot_id, NoShow.user_id)


def mark_no_show(slot_id: int, user_id: int) -> None:
    """Record a no-show for the given slot and user."""
    with Session() as session:
        no_show = NoShow(slot_id=slot_id, user_id=user_id)
        session.add(no_show)
        session.commit()
        logger.info("Marked no-show for slot_id=%s user_id=%s", slot_id, user_id)


def get_no_show_rate(resource_id: int) -> float:
    """
    Return the no-show rate for a resource.

    Rate = no_show_count / total_scheduled_slots for that resource.
    Returns 0.0 when the resource has no scheduled slots.
    """
    with Session() as session:
        no_show_count = session.scalar(
            select(func.count(NoShow.id))
            .join(Slot, NoShow.slot_id == Slot.id)
            .where(Slot.resource_id == resource_id)
        ) or 0

        total_slots = session.scalar(
            select(func.count(Slot.id)).where(Slot.resource_id == resource_id)
        ) or 0

        if total_slots == 0:
            logger.warning("No slots found for resource_id=%s", resource_id)
            return 0.0

        rate = no_show_count / total_slots
        logger.info(
            "No-show rate for resource_id=%s: %s (%s/%s)",
            resource_id,
            rate,
            no_show_count,
            total_slots,
        )
        return rate


class NoShowTracker:
    """
    Backwards-compatible tracker class that delegates to the module-level API.
    """

    @staticmethod
    def mark_no_show(slot_id: int, user_id: int) -> None:
        mark_no_show(slot_id, user_id)

    @staticmethod
    def get_no_show_rate(resource_id: int) -> float:
        return get_no_show_rate(resource_id)


def _selftest() -> None:
    """Offline self-test using a temporary SQLite database."""
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        db_path = os.path.join(temp_dir.name, "no_show_tracker.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)

        # Bind the module's session factory to the temporary engine.
        global Session
        Session = sessionmaker(bind=engine)

        # Create all tables required by this module.
        IntPKModel.metadata.create_all(engine)

        # Set up slots for two resources (canonical Slot requires start/end).
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        with Session() as session:
            resource_1_slots = [
                Slot(resource_id=1, start=now, end=now + timedelta(hours=1)),
                Slot(resource_id=1, start=now + timedelta(hours=2), end=now + timedelta(hours=3)),
                Slot(resource_id=1, start=now + timedelta(hours=4), end=now + timedelta(hours=5)),
            ]
            resource_2_slot = Slot(resource_id=2, start=now, end=now + timedelta(hours=1))
            session.add_all([*resource_1_slots, resource_2_slot])
            session.commit()
            slot_1_ids = [s.id for s in resource_1_slots]
            slot_2_id = resource_2_slot.id

        # Mark no-shows: 2 of 3 slots for resource 1, 0 of 1 for resource 2.
        mark_no_show(slot_1_ids[0], 101)
        mark_no_show(slot_1_ids[2], 102)

        rate_1 = get_no_show_rate(1)
        assert abs(rate_1 - 2.0 / 3.0) < 1e-9, f"Expected 2/3, got {rate_1}"

        rate_2 = get_no_show_rate(2)
        assert rate_2 == 0.0, f"Expected 0.0, got {rate_2}"

        # Unknown resource with no slots should report 0.0.
        rate_3 = get_no_show_rate(999)
        assert rate_3 == 0.0, f"Expected 0.0 for unknown resource, got {rate_3}"

        # Verify records were persisted.
        with Session() as session:
            count = session.scalar(select(func.count(NoShow.id)))
        assert count == 2, f"Expected 2 no-show records, got {count}"

        # Verify class-based API mirrors the module-level functions.
        assert NoShowTracker.get_no_show_rate(1) == rate_1

        logger.info("_selftest passed successfully")
    finally:
        engine.dispose()
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
