"""Generated SQLAlchemy models. Do not hand-edit; regenerate from the domain."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Integer, String, Text, Boolean, DateTime, Float, JSON, func, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CareRecipient(Base):
    __tablename__ = "care_recipients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lives_at: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primary_doctor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    emergency_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)

class CareTask(Base):
    __tablename__ = "care_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipient_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)

class Medication(Base):
    __tablename__ = "medications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipient_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dose: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schedule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prescriber: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)

class DoseLog(Base):
    __tablename__ = "dose_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    medication_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("medications.id", ondelete="CASCADE"), index=True, nullable=True)
    given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    given_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    taken: Mapped[bool | None] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipient_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    with_whom: Mapped[str | None] = mapped_column(String(255), nullable=True)
    at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    driver: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="scheduled", index=True)

class Update(Base):
    __tablename__ = "updates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipient_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
