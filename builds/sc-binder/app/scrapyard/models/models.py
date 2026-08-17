"""Generated SQLAlchemy models. Do not hand-edit; regenerate from the domain."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Integer, String, Text, Boolean, DateTime, Float, JSON, func, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from scrapyard.security.pq_field_encryption import PQEncryptedString  # hybrid PQ encryption at rest


class Base(DeclarativeBase):
    pass


class Child(Base):
    __tablename__ = "children"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    first_name: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'children.first_name'), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(255), nullable=True)
    school: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    diagnosis: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'children.diagnosis'), nullable=True)
    notes: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'children.notes'), nullable=True)
    promised_minutes_week: Mapped[int | None] = mapped_column(Integer, nullable=True)

class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    child_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("children.id", ondelete="CASCADE"), index=True, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(255), nullable=True)
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attendees: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'meetings.attendees'), nullable=True)
    notes: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'meetings.notes'), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="requested", index=True)

class Correspondence(Base):
    __tablename__ = "correspondences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    child_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("children.id", ondelete="CASCADE"), index=True, nullable=True)
    direction: Mapped[str | None] = mapped_column(String(255), nullable=True)
    with_whom: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subject: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'correspondences.subject'), nullable=True)
    body: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'correspondences.body'), nullable=True)

class ServiceEntry(Base):
    __tablename__ = "service_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    child_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("children.id", ondelete="CASCADE"), index=True, nullable=True)
    service: Mapped[str | None] = mapped_column(String(255), nullable=True)
    minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered: Mapped[bool | None] = mapped_column(Boolean, default=False)

class ActionItem(Base):
    __tablename__ = "action_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    child_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("children.id", ondelete="CASCADE"), index=True, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)
