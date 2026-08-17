"""Generated SQLAlchemy models. Do not hand-edit; regenerate from the domain."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Integer, String, Text, Boolean, DateTime, Float, JSON, func, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenancy(Base):
    __tablename__ = "tenancies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    landlord: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deposit_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    move_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    move_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_deadline_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)

class EvidenceShot(Base):
    __tablename__ = "evidence_shots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    tenancy_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tenancies.id", ondelete="CASCADE"), index=True, nullable=True)
    phase: Mapped[str | None] = mapped_column(String(255), nullable=True)
    room: Mapped[str | None] = mapped_column(String(255), nullable=True)
    photo_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    condition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Deduction(Base):
    __tablename__ = "deductions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    tenancy_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tenancies.id", ondelete="CASCADE"), index=True, nullable=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    landlord_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="contested", index=True)

class DisputeLetter(Base):
    __tablename__ = "dispute_letters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    tenancy_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tenancies.id", ondelete="CASCADE"), index=True, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    method: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
