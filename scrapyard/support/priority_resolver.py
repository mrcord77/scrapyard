"""
priority_resolver — Rule-driven ticket priority assignment with manual override and history.

### PART-META-JSON
{
  "name": "priority_resolver",
  "layer": "support",
  "purpose": "Assign support-ticket priorities: auto_assign_priority(ticket) evaluates active PriorityRule rows (ordered by fallback_order then newest version first) whose JSON conditions are equality/membership matches on Ticket fields, records the outcome in TicketPriority history with its source rule, and falls back to MEDIUM when nothing matches; set_priority() records a manual override. Every assignment is an append-only history row.",
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "_configure_engine(engine) once; PriorityRule rows seeded by the composing app ({'impact': 'high'} style conditions, priority as PriorityEnum value); auto_assign_priority(Ticket(...)); set_priority(ticket_id, PriorityEnum).",
  "outputs": "PriorityEnum decisions; TicketPriority audit rows with source 'manual', 'rule:<name>:v<n>', or 'fallback'.",
  "files_created": [],
  "security_notes": "Whoever can write PriorityRule rows controls triage for every ticket - treat rule management as an admin-only surface. Rule conditions are plain JSON compared with ==/membership (no eval, no regex), so rules cannot execute code. set_priority accepts any ticket_id without existence or permission checks, and history rows carry no actor identity - add caller attribution upstream if audits require it. A rule whose priority int is not a valid PriorityEnum raises ValueError at match time (selftest covers valid values only).",
  "ai_usage": "_configure_engine(engine); seed PriorityRule rows; p = auto_assign_priority(Ticket(id=1, impact='high', urgency='high')).",
  "example": "from scrapyard.support.priority_resolver import auto_assign_priority, set_priority, PriorityEnum",
  "import_path": "scrapyard.support.priority_resolver"
}
### END-PART-META
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Callable, Dict, Optional
import inspect
import logging
import os
import tempfile

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    JSON,
    String,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel


_logger = logging.getLogger(__name__)


class PriorityEnum(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Ticket:
    id: int
    subject: str = ""
    description: str = ""
    category: Optional[str] = None
    impact: Optional[str] = None
    urgency: Optional[str] = None
    customer_tier: Optional[str] = None
    sla_breach: bool = False


class PriorityRule(IntPKModel):
    __tablename__ = "priority_rule"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    conditions: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fallback_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


class TicketPriority(IntPKModel):
    __tablename__ = "ticket_priority"

    ticket_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


_engine: Optional[Any] = None
_Session: Optional[Callable[[], Session]] = None


def _configure_engine(engine: Any) -> None:
    global _engine, _Session
    _engine = engine
    _Session = sessionmaker(bind=engine, class_=Session)


@contextmanager
def _session_scope():
    if _Session is None:
        raise RuntimeError("priority_resolver engine has not been configured")
    session = _Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _rule_matches(rule: PriorityRule, ticket: Ticket) -> bool:
    conditions = rule.conditions or {}
    for key, expected in conditions.items():
        if not hasattr(ticket, key):
            return False
        actual = getattr(ticket, key)
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def set_priority(ticket_id: int, priority: PriorityEnum) -> None:
    if not isinstance(priority, PriorityEnum):
        raise TypeError(f"priority must be a PriorityEnum, got {type(priority).__name__}")
    with _session_scope() as session:
        entry = TicketPriority(
            ticket_id=ticket_id,
            priority=priority.value,
            source="manual",
        )
        session.add(entry)
    _logger.info("Manual priority %s set for ticket %s", priority.name, ticket_id)


def auto_assign_priority(ticket: Ticket) -> PriorityEnum:
    with _session_scope() as session:
        rules = session.scalars(
            select(PriorityRule)
            .where(PriorityRule.is_active == True)
            .order_by(PriorityRule.fallback_order.asc(), PriorityRule.version.desc())
        ).all()

        for rule in rules:
            if _rule_matches(rule, ticket):
                result = PriorityEnum(rule.priority)
                entry = TicketPriority(
                    ticket_id=ticket.id,
                    priority=result.value,
                    source=f"rule:{rule.name}:v{rule.version}",
                )
                session.add(entry)
                _logger.info(
                    "Auto-assigned priority %s to ticket %s via %s",
                    result.name,
                    ticket.id,
                    entry.source,
                )
                return result

        result = PriorityEnum.MEDIUM
        entry = TicketPriority(
            ticket_id=ticket.id,
            priority=result.value,
            source="fallback",
        )
        session.add(entry)
        _logger.info("Fallback priority %s assigned to ticket %s", result.name, ticket.id)
        return result


def _selftest() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "priority_resolver_test.db")
        engine = create_engine(f"sqlite:///{db_path}", future=True)
        IntPKModel.metadata.create_all(engine)
        _configure_engine(engine)

        # ORM table mapping and signatures
        assert PriorityRule.__tablename__ == "priority_rule"
        assert TicketPriority.__tablename__ == "ticket_priority"

        set_sig = inspect.signature(set_priority)
        assert list(set_sig.parameters.keys()) == ["ticket_id", "priority"]
        assert set_sig.return_annotation is None

        auto_sig = inspect.signature(auto_assign_priority)
        assert list(auto_sig.parameters.keys()) == ["ticket"]
        assert auto_sig.return_annotation == PriorityEnum

        # Seed rule set
        with Session(engine) as session:
            session.add_all(
                [
                    PriorityRule(
                        name="critical_rule",
                        version=1,
                        conditions={"impact": "high", "urgency": "high"},
                        priority=PriorityEnum.CRITICAL.value,
                        is_active=True,
                        fallback_order=1,
                    ),
                    PriorityRule(
                        name="high_rule",
                        version=2,
                        conditions={"impact": "medium"},
                        priority=PriorityEnum.HIGH.value,
                        is_active=True,
                        fallback_order=2,
                    ),
                    PriorityRule(
                        name="inactive_rule",
                        version=1,
                        conditions={"impact": "low"},
                        priority=PriorityEnum.LOW.value,
                        is_active=False,
                        fallback_order=0,
                    ),
                    PriorityRule(
                        name="billing_rule",
                        version=1,
                        conditions={"category": "billing"},
                        priority=PriorityEnum.HIGH.value,
                        is_active=True,
                        fallback_order=3,
                    ),
                    PriorityRule(
                        name="billing_rule",
                        version=2,
                        conditions={"category": "billing"},
                        priority=PriorityEnum.MEDIUM.value,
                        is_active=True,
                        fallback_order=3,
                    ),
                ]
            )
            session.commit()

        # Rule-based assignment
        t1 = Ticket(id=1, impact="high", urgency="high", category="tech")
        assert auto_assign_priority(t1) == PriorityEnum.CRITICAL

        t2 = Ticket(id=2, impact="medium", urgency="low", category="tech")
        assert auto_assign_priority(t2) == PriorityEnum.HIGH

        # Fallback
        t3 = Ticket(id=3, impact="low", urgency="low", category="other")
        assert auto_assign_priority(t3) == PriorityEnum.MEDIUM

        # Versioning: newest version evaluated first
        t4 = Ticket(id=4, impact="low", urgency="low", category="billing")
        assert auto_assign_priority(t4) == PriorityEnum.MEDIUM

        # Manual override
        set_priority(5, PriorityEnum.LOW)
        with Session(engine) as session:
            rows = session.scalars(
                select(TicketPriority).where(TicketPriority.ticket_id == 5)
            ).all()
            assert len(rows) == 1
            assert rows[0].priority == PriorityEnum.LOW.value
            assert rows[0].source == "manual"

        # History for auto-assigned tickets
        with Session(engine) as session:
            count = session.scalar(
                select(func.count())
                .select_from(TicketPriority)
                .where(TicketPriority.ticket_id.in_([1, 2, 3, 4]))
            )
            assert count == 4

        engine.dispose()


if __name__ == "__main__":
    _selftest()
