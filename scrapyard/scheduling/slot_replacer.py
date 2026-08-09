"""
slot_replacer — Replaces and reschedules existing scheduling slots with validation, conflict detection, and an in-memory audit log.

### PART-META-JSON
{
  "name": "slot_replacer",
  "layer": "scheduling",
  "purpose": "Replaces and reschedules existing scheduling slots: validates timezone-aware intervals, detects overlaps against other slots with a configurable conflict policy (raise/ignore), and records every change in an in-memory audit log. Uses the canonical Slot model owned by scrapyard.scheduling.slot_manager (no model of its own).",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model", "scrapyard.scheduling.slot_manager"],
  "inputs": "slot_id (int), timezone-aware new start/end datetimes or an integer minute offset; an active SQLAlchemy Session bound via _using_session.",
  "outputs": "Mutates the Slot row in place; appends change records to the audit log; raises TypeError/ValueError on invalid input, missing slot, or conflict.",
  "files_created": [],
  "security_notes": "No authorization is performed: callers must verify the acting user may modify the slot. The audit log is process-local and in-memory only (lost on restart, not shared across workers) - it is a debugging aid, not a compliance trail. Overlap check under the 'ignore' policy will silently create double-bookings by design.",
  "ai_usage": "Bind a session with _using_session(session), then call replace_slot or reschedule_slot.",
  "example": "from scrapyard.scheduling.slot_replacer import replace_slot, reschedule_slot",
  "import_path": "scrapyard.scheduling.slot_replacer"
}
### END-PART-META
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from scrapyard.database.base_model import IntPKModel

# Canonical-owner pattern: slot_manager owns the Slot model for the
# scheduling layer; this part imports it instead of declaring a duplicate.
from scrapyard.scheduling.slot_manager import Slot

logger = logging.getLogger(__name__)

#: Default conflict handling policy.
SUPPORTED_POLICIES = ("raise", "ignore")
_conflict_policy: str = "raise"

#: In-memory audit log of changes.
_audit_log: List[Dict[str, Any]] = []

#: Session context used by the public API.
_current_session: ContextVar[Optional[Session]] = ContextVar(
    "slot_replacer_session", default=None
)


def set_conflict_policy(policy: str) -> None:
    """Set the global conflict resolution policy.

    Args:
        policy: One of ``"raise"`` or ``"ignore"``.

    Raises:
        ValueError: If *policy* is not supported.
    """
    if policy not in SUPPORTED_POLICIES:
        raise ValueError(f"Unsupported conflict policy: {policy!r}")
    global _conflict_policy
    _conflict_policy = policy


def get_conflict_policy() -> str:
    """Return the current conflict resolution policy."""
    return _conflict_policy


def get_audit_log() -> List[Dict[str, Any]]:
    """Return a shallow copy of the audit log."""
    return list(_audit_log)


def clear_audit_log() -> None:
    """Clear the in-memory audit log."""
    _audit_log.clear()


@contextmanager
def _using_session(session: Session) -> Iterator[Session]:
    """Bind *session* as the active session for the public API."""
    token = _current_session.set(session)
    try:
        yield session
    finally:
        _current_session.reset(token)


def _get_session() -> Session:
    """Return the currently active session or raise."""
    session = _current_session.get()
    if session is None:
        raise RuntimeError("No active SQLAlchemy session for slot_replacer")
    return session


def _validate_datetime(value: Any, name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


def _validate_interval(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValueError("end time must be strictly after start time")


def _find_overlap(session: Session, slot_id: int, start: datetime, end: datetime) -> Optional[Slot]:
    """Return the first overlapping slot, excluding *slot_id*."""
    stmt = select(Slot).where(Slot.id != slot_id)
    for other in session.execute(stmt).scalars():
        if other.start_time < end and other.end_time > start:
            return other
    return None


def _record_audit(
    operation: str,
    slot_id: int,
    old_start: datetime,
    old_end: datetime,
    new_start: datetime,
    new_end: datetime,
) -> None:
    _audit_log.append(
        {
            "operation": operation,
            "slot_id": slot_id,
            "old_start": old_start,
            "old_end": old_end,
            "new_start": new_start,
            "new_end": new_end,
            "timestamp": datetime.now(timezone.utc),
        }
    )


def replace_slot(slot_id: int, new_start: datetime, new_end: datetime) -> None:
    """Replace a slot with new start/end times.

    Args:
        slot_id: Primary key of the slot to update.
        new_start: New timezone-aware start time.
        new_end: New timezone-aware end time.

    Raises:
        TypeError: If inputs are of the wrong type.
        ValueError: If the slot is missing, times are invalid, or a conflict occurs.
    """
    if not isinstance(slot_id, int):
        raise TypeError(f"slot_id must be int, got {type(slot_id).__name__}")

    _validate_datetime(new_start, "new_start")
    _validate_datetime(new_end, "new_end")
    _validate_interval(new_start, new_end)

    session = _get_session()
    slot = session.get(Slot, slot_id)
    if slot is None:
        raise ValueError(f"Slot with id {slot_id} not found")

    overlap = _find_overlap(session, slot_id, new_start, new_end)
    if overlap is not None and _conflict_policy == "raise":
        raise ValueError(
            f"Replacement overlaps with existing slot {overlap.id} "
            f"({overlap.start_time} - {overlap.end_time})"
        )

    old_start, old_end = slot.start_time, slot.end_time
    slot.start_time = new_start
    slot.end_time = new_end
    session.flush()

    _record_audit("replace", slot_id, old_start, old_end, new_start, new_end)
    logger.debug("Replaced slot %s: %s -> %s", slot_id, old_start, new_end)


def reschedule_slot(slot_id: int, offset_minutes: int) -> None:
    """Reschedule a slot by *offset_minutes*.

    Args:
        slot_id: Primary key of the slot to update.
        offset_minutes: Number of minutes to shift the slot (may be negative).

    Raises:
        TypeError: If inputs are of the wrong type.
        ValueError: If the slot is missing or the new time is invalid/conflicting.
    """
    if not isinstance(slot_id, int):
        raise TypeError(f"slot_id must be int, got {type(slot_id).__name__}")
    if not isinstance(offset_minutes, int):
        raise TypeError(
            f"offset_minutes must be int, got {type(offset_minutes).__name__}"
        )

    session = _get_session()
    slot = session.get(Slot, slot_id)
    if slot is None:
        raise ValueError(f"Slot with id {slot_id} not found")

    offset = timedelta(minutes=offset_minutes)
    new_start = slot.start_time + offset
    new_end = slot.end_time + offset

    # Let replace_slot handle validation, overlap checks and audit.
    replace_slot(slot_id, new_start, new_end)


def _selftest() -> None:
    """Offline self-test for the slot_replacer module."""
    import tempfile

    from sqlalchemy import create_engine

    clear_audit_log()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "slot_replacer_test.db")
        engine = create_engine(f"sqlite:///{db_path}", future=True)

        IntPKModel.metadata.create_all(engine)

        session = Session(engine)

        # Ensure no commit happens during the test.
        original_commit = session.commit

        def _forbidden_commit() -> None:
            raise AssertionError("database commit occurred during selftest")

        session.commit = _forbidden_commit  # type: ignore[method-assign]

        try:
            with _using_session(session):
                # Create a baseline slot.
                slot = Slot(
                    start_time=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                    end_time=datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
                )
                session.add(slot)
                session.flush()

                # 1. Replace a slot.
                new_start = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)
                new_end = datetime(2024, 1, 2, 13, 0, tzinfo=timezone.utc)
                replace_slot(slot.id, new_start, new_end)
                assert slot.start_time == new_start
                assert slot.end_time == new_end

                # 2. Reschedule a slot.
                reschedule_slot(slot.id, 30)
                assert slot.start_time == new_start + timedelta(minutes=30)
                assert slot.end_time == new_end + timedelta(minutes=30)

                # 3. Invalid slot_id type.
                try:
                    replace_slot("not-an-int", new_start, new_end)
                    raise AssertionError("string slot_id accepted")
                except TypeError:
                    pass

                # 4. Missing slot.
                try:
                    replace_slot(999_999, new_start, new_end)
                    raise AssertionError("missing slot accepted")
                except ValueError:
                    pass

                # 5. Naive datetime rejected.
                try:
                    replace_slot(
                        slot.id,
                        datetime(2024, 1, 1, 10, 0),
                        datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
                    )
                    raise AssertionError("naive datetime accepted")
                except ValueError:
                    pass

                # 6. End before start rejected.
                try:
                    replace_slot(slot.id, new_end, new_start)
                    raise AssertionError("end <= start accepted")
                except ValueError:
                    pass

                # 7. Bad offset type.
                try:
                    reschedule_slot(slot.id, "thirty")
                    raise AssertionError("string offset accepted")
                except TypeError:
                    pass

                # 8. Overlap detection.
                other = Slot(
                    start_time=datetime(2024, 1, 4, 9, 0, tzinfo=timezone.utc),
                    end_time=datetime(2024, 1, 4, 12, 0, tzinfo=timezone.utc),
                )
                session.add(other)
                session.flush()

                try:
                    replace_slot(
                        slot.id,
                        datetime(2024, 1, 4, 10, 0, tzinfo=timezone.utc),
                        datetime(2024, 1, 4, 11, 0, tzinfo=timezone.utc),
                    )
                    raise AssertionError("overlapping replacement accepted")
                except ValueError:
                    pass

                # 9. Timezone-aware replacement.
                cet = timezone(timedelta(hours=1))
                replace_slot(
                    slot.id,
                    datetime(2024, 1, 5, 14, 0, tzinfo=cet),
                    datetime(2024, 1, 5, 15, 0, tzinfo=cet),
                )
                assert slot.start_time.tzinfo == cet
                assert slot.end_time.tzinfo == cet

                # 10. Audit log recorded changes.
                assert len(get_audit_log()) >= 3

                # 11. Conflict policy can be configured.
                set_conflict_policy("ignore")
                replace_slot(
                    slot.id,
                    datetime(2024, 1, 4, 10, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 4, 11, 0, tzinfo=timezone.utc),
                )
                set_conflict_policy("raise")

        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
