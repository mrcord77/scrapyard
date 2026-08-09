"""
ab_testing — Assign + measure experiment variants.

### PART-META-JSON
{
  "name": "ab_testing",
  "layer": "analytics",
  "purpose": "Assign + measure experiment variants.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: assign(experiment, subject_id, variants, hash_alg, salt); assign_with_metadata(experiment, subject_id, variants, hash_alg, salt); get_assignments(experiment, subject_ids, variants); bulk_assign(experiment, subject_ids, variants, hash_alg, salt); split_summary(experiment, subject_ids, variants, page, page_size); ABTestingConfig(...); ExperimentAssignment(...); ExperimentAssignmentRecord(...) (plus more).",
  "outputs": "Returns: assign -> str; assign_with_metadata -> dict[str, str | int]; get_assignments -> dict[str, dict[str, str]]; bulk_assign -> dict[str, str]; split_summary -> dict[str, int].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `assign` from `scrapyard.analytics.ab_testing` and call it as shown in `example`; run `py -m scrapyard.analytics.ab_testing` to see its offline selftest.",
  "example": "from scrapyard.analytics.ab_testing import assign",
  "import_path": "scrapyard.analytics.ab_testing"
}
### END-PART-META
"""
from __future__ import annotations
import hashlib
import logging
import threading
import typing as t
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, Session
from sqlalchemy.exc import SQLAlchemyError
from scrapyard.database.base_model import IntPKModel

STATUS = "core"

logger = logging.getLogger(__name__)

class ABTestingConfig(BaseModel):
    hash_alg: str = "sha256"
    default_salt: t.Optional[str] = None
    max_variants: int = 10

_config = ABTestingConfig()

class ExperimentAssignment(BaseModel):
    """API-facing assignment record."""
    experiment: str
    subject_id: str
    variant: str

class ExperimentAssignmentRecord(IntPKModel):
    """ORM model for persisted assignments (the pydantic model cannot be
    stored in a session)."""
    __tablename__ = "experiment_assignments"

    experiment: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    variant: Mapped[str] = mapped_column(String(64), nullable=False)

# In-process event store backing record_event/get_event_stats.
_EVENTS: list[dict] = []
_EVENTS_LOCK = threading.Lock()

def assign(experiment: str, subject_id: str, variants: tuple[str, ...] = ("A", "B"), hash_alg: str = "sha256", salt: str | None = None) -> str:
    """Deterministic, sticky bucketing: same subject always gets same variant."""
    if not isinstance(subject_id, str):
        raise ValueError("subject_id must be a non-empty string")
    h = int(hashlib.new(hash_alg, f"{experiment}:{subject_id}{salt or ''}".encode()).hexdigest(), 16)
    return variants[h % len(variants)]

def assign_with_metadata(experiment: str, subject_id: str, variants: tuple[str, ...] = ("A", "B"), hash_alg: str = "sha256", salt: str | None = None) -> dict[str, str | int]:
    """Assigns a variant and returns metadata for audit/metrics tracking."""
    if not isinstance(subject_id, str):
        raise ValueError("subject_id must be a non-empty string")
    variant = assign(experiment, subject_id, variants, hash_alg, salt)
    return {"experiment": experiment, "subject_id": subject_id, "variant": variant}

def get_assignments(experiment: str, subject_ids: list[str], variants: tuple[str, ...] = ("A", "B")) -> dict[str, dict[str, str]]:
    """Retrieves historical assignments for a given experiment and subject IDs."""
    return {s: assign(experiment, s, variants) for s in subject_ids}

def bulk_assign(experiment: str, subject_ids: list[str], variants: tuple[str, ...] = ("A", "B"), hash_alg: str = "sha256", salt: str | None = None) -> dict[str, str]:
    """Efficient batch assignment of subjects to variants."""
    if not all(isinstance(s, str) for s in subject_ids):
        raise ValueError("All subject_ids must be non-empty strings")
    return {s: assign(experiment, s, variants, hash_alg, salt) for s in subject_ids}

def split_summary(experiment: str, subject_ids: list[str], variants: tuple[str, ...] = ("A", "B"), page: int = 1, page_size: int = 100) -> dict[str, int]:
    """Variant counts for one page of subject_ids (pagination applies to the
    subject list, then counts are computed over that page)."""
    if not all(isinstance(s, str) for s in subject_ids):
        raise ValueError("All subject_ids must be non-empty strings")
    if page < 1 or page_size < 1:
        raise ValueError("page and page_size must be >= 1")
    window = subject_ids[(page - 1) * page_size : page * page_size]
    out = {v: 0 for v in variants}
    for s in window:
        out[assign(experiment, s, variants)] += 1
    return out

def record_event(event_type: str, experiment: str, subject_id: str, variant: str, metadata: dict | None = None) -> None:
    """Record a user action in the in-process event store for later stats."""
    if not isinstance(subject_id, str) or not subject_id:
        raise ValueError("subject_id must be a non-empty string")
    with _EVENTS_LOCK:
        _EVENTS.append({
            "event_type": event_type,
            "experiment": experiment,
            "subject_id": subject_id,
            "variant": variant,
            "metadata": metadata or {},
        })
    logger.debug("Event recorded: %s experiment=%s subject=%s variant=%s",
                 event_type, experiment, subject_id, variant)

def clear_events() -> None:
    """Reset the in-process event store (test/maintenance helper)."""
    with _EVENTS_LOCK:
        _EVENTS.clear()

def get_event_stats(experiment: str, variant: str | None = None, event_type: str | None = None) -> dict[str, int]:
    """Counts over recorded events, filtered by experiment/variant/event_type."""
    with _EVENTS_LOCK:
        rows = [e for e in _EVENTS if e["experiment"] == experiment]
    if variant is not None:
        rows = [e for e in rows if e["variant"] == variant]
    if event_type is not None:
        rows = [e for e in rows if e["event_type"] == event_type]
    per_variant: dict[str, int] = {}
    for e in rows:
        per_variant[e["variant"]] = per_variant.get(e["variant"], 0) + 1
    return {"total_events": len(rows), **{f"variant_{k}": v for k, v in per_variant.items()}}

def validate_subject_id(subject_id: str) -> None:
    """Validates the subject ID."""
    if not isinstance(subject_id, str) or not subject_id:
        raise ValueError("subject_id must be a non-empty string")

def configure_ab_testing(hash_alg: str = "sha256", default_salt: t.Optional[str] = None, max_variants: int = 10) -> None:
    """Centralized configuration for AB testing (validated and stored)."""
    global _config
    hashlib.new(hash_alg)  # raises ValueError for unsupported algorithms
    if max_variants < 2:
        raise ValueError("max_variants must be at least 2")
    _config = ABTestingConfig(hash_alg=hash_alg, default_salt=default_salt, max_variants=max_variants)

def get_ab_testing_config() -> ABTestingConfig:
    return _config

def save_assignments(session: Session, experiment: str, subject_ids: list[str], variants: tuple[str, ...] = ("A", "B")) -> None:
    """Persist deterministic assignments as ORM rows."""
    for s_id in subject_ids:
        variant = assign(experiment, s_id, variants)
        session.add(ExperimentAssignmentRecord(experiment=experiment, subject_id=s_id, variant=variant))
    try:
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))

def get_assignments_from_db(session: Session, experiment: str) -> dict[str, str]:
    """Retrieves persisted assignments from the database."""
    query = session.query(ExperimentAssignmentRecord).filter_by(experiment=experiment)
    return {assignment.subject_id: assignment.variant for assignment in query.all()}


def _selftest() -> None:
    import tempfile, os
    from sqlalchemy import create_engine

    # Deterministic, sticky bucketing
    v1 = assign("exp1", "user-1")
    assert v1 in ("A", "B")
    assert all(assign("exp1", "user-1") == v1 for _ in range(5)), "assignment must be sticky"
    # Different experiments may differ; distribution covers both variants
    buckets = {assign("exp1", f"u{i}") for i in range(50)}
    assert buckets == {"A", "B"}
    # Salt changes the mapping for at least one subject
    assert any(assign("exp1", f"u{i}") != assign("exp1", f"u{i}", salt="s2") for i in range(50))

    meta = assign_with_metadata("exp1", "user-1")
    assert meta["variant"] == v1 and meta["experiment"] == "exp1"

    bulk = bulk_assign("exp1", ["a", "b", "c"])
    assert set(bulk) == {"a", "b", "c"}
    assert get_assignments("exp1", ["a", "b"]) == {k: bulk[k] for k in ("a", "b")}

    # split_summary: paginates the subject list, counts within the page
    ids = [f"s{i}" for i in range(10)]
    full = split_summary("exp1", ids, page=1, page_size=100)
    assert sum(full.values()) == 10
    p1 = split_summary("exp1", ids, page=1, page_size=4)
    p2 = split_summary("exp1", ids, page=2, page_size=4)
    p3 = split_summary("exp1", ids, page=3, page_size=4)
    assert sum(p1.values()) == 4 and sum(p2.values()) == 4 and sum(p3.values()) == 2
    try:
        split_summary("exp1", ids, page=0)
        assert False
    except ValueError:
        pass

    # events: recorded and countable, not constant
    clear_events()
    record_event("click", "exp1", "user-1", v1)
    record_event("click", "exp1", "user-2", "B")
    record_event("convert", "exp1", "user-2", "B")
    stats = get_event_stats("exp1")
    assert stats["total_events"] == 3
    assert get_event_stats("exp1", event_type="convert")["total_events"] == 1
    assert get_event_stats("exp1", variant="B")["total_events"] >= 2
    assert get_event_stats("other")["total_events"] == 0
    try:
        record_event("click", "exp1", "", "A")
        assert False
    except ValueError:
        pass
    clear_events()

    # config validation
    configure_ab_testing("sha1", default_salt="x", max_variants=4)
    assert get_ab_testing_config().hash_alg == "sha1"
    try:
        configure_ab_testing("not-a-hash")
        assert False
    except ValueError:
        pass
    configure_ab_testing()  # restore defaults

    validate_subject_id("ok")
    try:
        validate_subject_id("")
        assert False
    except ValueError:
        pass

    # DB persistence uses the ORM record
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as session:
                save_assignments(session, "exp-db", ["x", "y", "z"])
                stored = get_assignments_from_db(session, "exp-db")
                assert stored == bulk_assign("exp-db", ["x", "y", "z"])
                assert get_assignments_from_db(session, "missing") == {}
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("ab_testing selftest OK")
