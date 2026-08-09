"""
access_review_service — Persist access-review reports and approve/revoke decisions with an audit trail.

### PART-META-JSON
{
  "name": "access_review_service",
  "layer": "audit_governance",
  "purpose": "Persist access-review outcomes: generate_review_report() writes/updates an AccessReviewResult row per review_id, approve_or_revoke_access() records the decision plus an AccessReviewAction audit-trail row. NOTE: the report body itself is a canned scaffold (fixed findings/recommendation strings), not an actual entitlement analysis - real review logic must be supplied by the composing app; this part is the persistence and audit layer.",
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure(engine) once at startup; then generate_review_report(review_id) and approve_or_revoke_access(review_id, 'approve'|'revoke').",
  "outputs": "Report/decision dicts; AccessReviewResult rows (unique per review_id) and append-only AccessReviewAction rows.",
  "files_created": [],
  "security_notes": "No authentication or authorization: any caller with the module imported can approve or revoke any review_id, so wrap these functions behind an admin permission check. Actions are recorded without an actor identity (no user column on AccessReviewAction) - add caller attribution in the composing app if your audit requirements need it. Invalid actions raise ValueError before any write. The generated 'findings' are placeholder strings; do not present them as a completed security review.",
  "ai_usage": "configure(engine); report = generate_review_report(rid); approve_or_revoke_access(rid, 'approve').",
  "example": "from scrapyard.audit_governance.access_review_service import configure, generate_review_report",
  "import_path": "scrapyard.audit_governance.access_review_service"
}
### END-PART-META
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

import logging
import os
import tempfile

logger = logging.getLogger(__name__)


PART_META = {
    "name": "scrapyard.audit_governance.access_review_service",
    "layer": "audit_governance",
}
__part_meta__ = PART_META


class AccessReviewResult(IntPKModel):
    """Persisted outcome of an access review."""
    __tablename__ = "access_review_result"
    __table_args__ = (
        UniqueConstraint("review_id", name="uq_access_review_result_review_id"),
    )

    review_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AccessReviewAction(IntPKModel):
    """Audit trail entry for approve/revoke actions."""
    __tablename__ = "access_review_action"

    review_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("access_review_result.review_id"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


_engine: Engine | None = None


def configure(engine: Engine) -> None:
    """Bind the service to a SQLAlchemy engine."""
    global _engine
    _engine = engine
    logger.debug("Access review service configured with engine %s", engine)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_report(review_id: int) -> dict[str, Any]:
    return {
        "review_id": review_id,
        "status": "pending",
        "generated_at": _utc_now().isoformat(),
        "findings": ["Entitlements reviewed", "No anomalies detected"],
        "recommendation": "Proceed with review decision",
    }


def _require_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Access review service has not been configured with an engine")
    return _engine


def generate_review_report(review_id: int) -> dict[str, Any]:
    """Generate and persist an access review report for *review_id*."""
    engine = _require_engine()
    report = _build_report(review_id)

    with Session(engine) as session:
        stmt = select(AccessReviewResult).where(
            AccessReviewResult.review_id == review_id
        )
        result = session.execute(stmt).scalar_one_or_none()

        if result is None:
            result = AccessReviewResult(
                review_id=review_id,
                status="pending",
                report=report,
            )
            session.add(result)
        else:
            result.report = report
            result.updated_at = _utc_now()

        session.commit()
        logger.info("Generated access review report for review_id=%s", review_id)

    return report


def approve_or_revoke_access(review_id: int, action: str) -> dict[str, Any]:
    """Record an approval or revocation for *review_id*."""
    engine = _require_engine()
    normalized = action.lower().strip()

    if normalized not in ("approve", "revoke"):
        raise ValueError(
            f"Invalid action {action!r}; expected 'approve' or 'revoke'"
        )

    new_status = "approved" if normalized == "approve" else "revoked"

    with Session(engine) as session:
        stmt = select(AccessReviewResult).where(
            AccessReviewResult.review_id == review_id
        )
        result = session.execute(stmt).scalar_one_or_none()

        if result is None:
            result = AccessReviewResult(
                review_id=review_id,
                status=new_status,
                report=_build_report(review_id),
            )
            session.add(result)
        else:
            result.status = new_status
            result.updated_at = _utc_now()

        performed_at = _utc_now()
        action_row = AccessReviewAction(
            review_id=review_id,
            action=normalized,
            performed_at=performed_at,
        )
        session.add(action_row)
        session.commit()

        logger.info(
            "Recorded %s action for review_id=%s", normalized, review_id
        )

    return {
        "review_id": review_id,
        "action": normalized,
        "status": new_status,
        "performed_at": performed_at.isoformat(),
    }


def _selftest() -> None:
    """Offline, self-contained validation using a temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "access_review_selftest.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        try:
            IntPKModel.metadata.create_all(engine)
            configure(engine)

            review_id = 1001
            report = generate_review_report(review_id)
            assert isinstance(report, dict)
            assert report["review_id"] == review_id
            assert report["status"] == "pending"

            with Session(engine) as session:
                result_row = session.execute(
                    select(AccessReviewResult).where(
                        AccessReviewResult.review_id == review_id
                    )
                ).scalar_one()
                assert result_row.review_id == review_id
                assert result_row.status == "pending"
                assert result_row.report == report

            approval = approve_or_revoke_access(review_id, "approve")
            assert approval["review_id"] == review_id
            assert approval["action"] == "approve"
            assert approval["status"] == "approved"

            with Session(engine) as session:
                result_row = session.execute(
                    select(AccessReviewResult).where(
                        AccessReviewResult.review_id == review_id
                    )
                ).scalar_one()
                assert result_row.status == "approved"

                action_rows = session.execute(
                    select(AccessReviewAction).where(
                        AccessReviewAction.review_id == review_id
                    )
                ).scalars().all()
                assert len(action_rows) == 1
                assert action_rows[0].action == "approve"

            revoke_id = 1002
            revocation = approve_or_revoke_access(revoke_id, "revoke")
            assert revocation["status"] == "revoked"

            with Session(engine) as session:
                result_row = session.execute(
                    select(AccessReviewResult).where(
                        AccessReviewResult.review_id == revoke_id
                    )
                ).scalar_one()
                assert result_row.status == "revoked"

            try:
                approve_or_revoke_access(review_id, "invalid")
                raise AssertionError("Expected ValueError for invalid action")
            except ValueError:
                pass

            logger.info("_selftest passed")
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
