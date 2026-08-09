"""
approval_request - Represent approval requests with lifecycle status, history, and soft deletion for audit.

### PART-META-JSON
{
  "name": "approval_request",
  "layer": "approvals_workfl",
  "purpose": "Represent approval requests with lifecycle status, history, and soft deletion for audit.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure(engine); submit_request(data) plus status transition helpers.",
  "outputs": "ApprovalRequest / RequestStatus / RequestHistory rows; soft-deleted rows retained for audit.",
  "files_created": [],
  "security_notes": "Requests are soft-deleted (never hard-deleted) so approval trails survive; every transition is written to RequestHistory. Input dicts are field-validated (ValidationError) before persistence. Requester identity is caller-supplied - authenticate upstream.",
  "ai_usage": "Import what you need from `scrapyard.approvals_workfl.approval_request`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.approvals_workfl.approval_request import configure",
  "import_path": "scrapyard.approvals_workfl.approval_request"
}
### END-PART-META
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, sessionmaker
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class ValidationError(ValueError):
    """Raised when request data fails validation."""


# ---------------------------------------------------------------------------
# Global session configuration (set by configure() or _selftest())
# ---------------------------------------------------------------------------
_engine: Optional[Any] = None
_Session: Optional[Any] = None


def configure(engine: Any) -> None:
    """Bind the module's operations to the supplied SQLAlchemy engine."""
    global _engine, _Session
    _engine = engine
    _Session = sessionmaker(bind=engine, expire_on_commit=False)


def _get_session() -> Session:
    if _Session is None:
        raise RuntimeError(
            "approval_request is not configured with a database engine. "
            "Call configure(engine) first."
        )
    return _Session()


def _ensure_statuses(session: Session) -> None:
    """Create the canonical status rows if they do not already exist."""
    expected = {
        "Draft": "Draft",
        "Submitted": "Submitted",
        "Approved": "Approved",
        "Rejected": "Rejected",
    }
    existing = {
        name
        for (name,) in session.execute(select(RequestStatus.name))
    }
    for name, label in expected.items():
        if name not in existing:
            session.add(RequestStatus(name=name, label=label))
    session.commit()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class RequestStatus(IntPKModel):
    """Canonical statuses for an approval request."""

    __tablename__ = "request_statuses"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    def __repr__(self) -> str:
        return f"<RequestStatus {self.name!r}>"


class ApprovalRequest(IntPKModel):
    """A single approval request and its current lifecycle state."""

    __tablename__ = "approval_requests"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    status_id: Mapped[int] = mapped_column(
        ForeignKey("request_statuses.id"), nullable=False, index=True
    )
    status: Mapped["RequestStatus"] = relationship("RequestStatus")

    approvers: Mapped[List[str]] = mapped_column(JSON, default=list)
    chain_parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("approval_requests.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    def soft_delete(self) -> None:
        """Mark this request as deleted without removing its audit trail."""
        self.deleted_at = datetime.now(timezone.utc)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def __repr__(self) -> str:
        return f"<ApprovalRequest {self.id} {self.title!r}>"


class RequestHistory(IntPKModel):
    """Immutable record of every state transition for an approval request."""

    __tablename__ = "request_history"

    request_id: Mapped[int] = mapped_column(
        ForeignKey("approval_requests.id"), nullable=False, index=True
    )
    from_status_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("request_statuses.id"), nullable=True
    )
    to_status_id: Mapped[int] = mapped_column(
        ForeignKey("request_statuses.id"), nullable=False
    )
    actor: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<RequestHistory request={self.request_id} to={self.to_status_id}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def submit_request(data: Dict[str, Any]) -> ApprovalRequest:
    """Validate and submit a new approval request, logging its initial state."""
    if not isinstance(data, dict):
        raise ValidationError("Request data must be a dictionary.")

    title = data.get("title")
    owner = data.get("owner")

    if not title or not isinstance(title, str) or not title.strip():
        raise ValidationError("Request must include a non-empty 'title'.")
    if not owner or not isinstance(owner, str) or not owner.strip():
        raise ValidationError("Request must include a non-empty 'owner'.")

    approvers = data.get("approvers", [])
    if not isinstance(approvers, list):
        raise ValidationError("'approvers' must be a list.")

    session = _get_session()
    try:
        _ensure_statuses(session)

        submitted_status = session.scalar(
            select(RequestStatus).where(RequestStatus.name == "Submitted")
        )

        request = ApprovalRequest(
            title=title.strip(),
            description=data.get("description"),
            owner=owner.strip(),
            status=submitted_status,
            approvers=approvers,
            submitted_at=datetime.now(timezone.utc),
        )
        session.add(request)
        session.flush()

        history = RequestHistory(
            request_id=request.id,
            from_status_id=None,
            to_status_id=submitted_status.id,
            actor=owner.strip(),
            note="Request submitted",
        )
        session.add(history)
        session.commit()
        return request
    finally:
        session.close()


def get_request_status(request_id: int) -> RequestStatus:
    """Return the current status of the approval request."""
    session = _get_session()
    try:
        request = session.get(ApprovalRequest, request_id)
        if request is None or request.deleted_at is not None:
            raise ValueError(f"Approval request {request_id} not found or deleted.")
        return request.status
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Self test
# ---------------------------------------------------------------------------
def _selftest() -> None:
    import os
    import tempfile
    import time

    start = time.time()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "approval_request_selftest.db")
        engine = create_engine(f"sqlite:///{db_path}", future=True, echo=False)
        configure(engine)

        try:
            IntPKModel.metadata.create_all(engine)

            # --- Model/table sanity checks ---
            assert ApprovalRequest.__tablename__ == "approval_requests"
            assert RequestHistory.__tablename__ == "request_history"
            assert RequestStatus.__tablename__ == "request_statuses"

            request_cols = {c.name for c in ApprovalRequest.__table__.columns}
            expected_request_cols = {
                "id",
                "title",
                "description",
                "owner",
                "status_id",
                "approvers",
                "chain_parent_id",
                "created_at",
                "submitted_at",
                "updated_at",
                "deleted_at",
            }
            assert expected_request_cols <= request_cols, (
                f"Missing approval_requests columns: "
                f"{expected_request_cols - request_cols}"
            )

            history_cols = {c.name for c in RequestHistory.__table__.columns}
            expected_history_cols = {
                "id",
                "request_id",
                "from_status_id",
                "to_status_id",
                "actor",
                "timestamp",
                "note",
            }
            assert expected_history_cols <= history_cols, (
                f"Missing request_history columns: "
                f"{expected_history_cols - history_cols}"
            )

            # --- Validation error on invalid data ---
            try:
                submit_request({})
                raise AssertionError("Expected ValidationError for empty data")
            except ValidationError:
                pass

            try:
                submit_request({"title": "Only title"})
                raise AssertionError("Expected ValidationError for missing owner")
            except ValidationError:
                pass

            # --- Submit a request ---
            request = submit_request(
                {
                    "title": "Scrapyard hydraulic pump",
                    "owner": "alice",
                    "description": "Need approval to list a salvaged pump",
                    "approvers": ["bob", "carol"],
                }
            )
            assert request.id is not None
            assert request.title == "Scrapyard hydraulic pump"
            assert request.owner == "alice"
            assert request.approvers == ["bob", "carol"]

            # --- Status check ---
            status = get_request_status(request.id)
            assert isinstance(status, RequestStatus)
            assert status.name == "Submitted"

            # --- History recorded the initial state ---
            with Session(engine) as session:
                history_entries = session.scalars(
                    select(RequestHistory).where(RequestHistory.request_id == request.id)
                ).all()
                assert len(history_entries) == 1
                entry = history_entries[0]
                assert entry.from_status_id is None
                assert entry.to_status_id == status.id
                assert entry.actor == "alice"

            # --- Soft deletion reflected in query results ---
            with Session(engine) as session:
                active_before = session.scalars(
                    select(ApprovalRequest).where(ApprovalRequest.deleted_at.is_(None))
                ).all()
                assert len(active_before) == 1

                req = session.get(ApprovalRequest, request.id)
                req.soft_delete()
                session.commit()

                active_after = session.scalars(
                    select(ApprovalRequest).where(ApprovalRequest.deleted_at.is_(None))
                ).all()
                assert len(active_after) == 0

            try:
                get_request_status(request.id)
                raise AssertionError("Expected ValueError for deleted request")
            except ValueError:
                pass

        finally:
            engine.dispose()

    elapsed = time.time() - start
    assert elapsed < 20, f"_selftest took {elapsed:.2f}s, must be under 20s"


if __name__ == "__main__":
    _selftest()
    print("approval_request selftest OK")
