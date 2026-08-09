"""
decision - Record approval decisions (approve/reject/abstain) with an append-only decision log.

### PART-META-JSON
{
  "name": "decision",
  "layer": "approvals_workfl",
  "purpose": "Record approval decisions (approve/reject/abstain) with an append-only decision log.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "record_decision(decision); get_decision_details(decision_id).",
  "outputs": "Decision rows plus DecisionLog audit entries.",
  "files_created": [],
  "security_notes": "Decisions are the audit anchor of the approval chain: the log is append-only and decisions are typed (enum), preventing free-text outcome spoofing. Decider identity is caller-supplied - authenticate upstream and record it verbatim.",
  "ai_usage": "Import what you need from `scrapyard.approvals_workfl.decision`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.approvals_workfl.decision import record_decision",
  "import_path": "scrapyard.approvals_workfl.decision"
}
### END-PART-META
"""
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import (
    String,
    DateTime,
    JSON,
    ForeignKey,
    Index,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
import logging
import tempfile

logger = logging.getLogger(__name__)


class DecisionType(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    PENDING = "pending"


# Module-level session factory. Consumers or _selftest must configure/bind it.
# expire_on_commit=False keeps returned/detached instances usable after commit.
Session = sessionmaker(expire_on_commit=False)


class Decision(IntPKModel):
    __tablename__ = "decisions"

    decision_type: Mapped[DecisionType] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decision_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_decision_type", "decision_type"),)


class DecisionLog(IntPKModel):
    __tablename__ = "decision_logs"

    decision_id: Mapped[int] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attribute_name: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    new_value: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def record_decision(decision: Decision) -> None:
    with Session() as session:
        if decision.id is None:
            existing = None
        else:
            existing = session.get(Decision, decision.id)

        if existing is None:
            decision.created_at = datetime.now(timezone.utc)
            session.add(decision)
            session.flush()
            session.add(
                DecisionLog(
                    decision_id=decision.id,
                    attribute_name="created",
                    old_value=None,
                    new_value={
                        "decision_type": _normalize_value(decision.decision_type),
                        "description": decision.description,
                        "decision_metadata": decision.decision_metadata,
                    },
                )
            )
            session.commit()
            return

        tracked_attributes = ("decision_type", "description", "decision_metadata")
        changed = False
        for attr in tracked_attributes:
            old_value = getattr(existing, attr)
            new_value = getattr(decision, attr)
            if old_value != new_value:
                session.add(
                    DecisionLog(
                        decision_id=existing.id,
                        attribute_name=attr,
                        old_value=_normalize_value(old_value),
                        new_value=_normalize_value(new_value),
                    )
                )
                setattr(existing, attr, new_value)
                changed = True

        if changed:
            session.commit()


def get_decision_details(decision_id: int) -> Optional[Decision]:
    with Session() as session:
        return session.get(Decision, decision_id)


def _selftest() -> None:
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    engine = create_engine(f"sqlite:///{temp_dir.name}/test_decisions.db")

    global Session
    Session.configure(bind=engine)

    try:
        Decision.metadata.create_all(engine)

        logger.info("Starting self-test for decision module")

        decision = Decision(
            decision_type=DecisionType.APPROVE,
            description="Test approval decision",
            decision_metadata={"item_id": 123},
        )

        record_decision(decision)
        assert decision.id is not None, "Decision should receive an ID after recording"

        recorded = get_decision_details(decision.id)
        assert recorded is not None, "Decision should be retrievable"
        assert recorded.decision_type == DecisionType.APPROVE, "Decision type mismatch"
        assert recorded.description == "Test approval decision", "Description mismatch"
        assert recorded.decision_metadata == {"item_id": 123}, "Metadata mismatch"

        with Session() as session:
            logs = (
                session.execute(
                    select(DecisionLog).where(DecisionLog.decision_id == decision.id)
                )
                .scalars()
                .all()
            )
        assert len(logs) == 1, "Creation should produce exactly one log entry"
        assert logs[0].attribute_name == "created", "First log should record creation"

        decision.description = "Updated approval description"
        decision.decision_metadata = {"item_id": 123, "reason": "valid"}
        record_decision(decision)

        updated = get_decision_details(decision.id)
        assert updated is not None, "Updated decision should be retrievable"
        assert updated.description == "Updated approval description", "Updated description mismatch"
        assert updated.decision_metadata == {"item_id": 123, "reason": "valid"}, "Updated metadata mismatch"

        with Session() as session:
            logs = (
                session.execute(
                    select(DecisionLog).where(DecisionLog.decision_id == decision.id)
                )
                .scalars()
                .all()
            )
        assert len(logs) == 3, "Should have creation log plus two modification logs"
        log_attributes = {log.attribute_name for log in logs}
        assert "created" in log_attributes, "Creation log missing"
        assert "description" in log_attributes, "Description change not logged"
        assert "decision_metadata" in log_attributes, "Metadata change not logged"

        logger.info("Self-test completed successfully")
    finally:
        engine.dispose()
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
