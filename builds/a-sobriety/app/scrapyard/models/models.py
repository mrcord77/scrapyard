"""Generated SQLAlchemy models. Do not hand-edit; regenerate from the domain."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Integer, String, Text, Boolean, DateTime, Float, JSON, func, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from scrapyard.security.pq_field_encryption import PQEncryptedString  # hybrid PQ encryption at rest


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "app_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sobriety_date: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_anonymous: Mapped[bool | None] = mapped_column(Boolean, default=False)

class Membership(Base):
    __tablename__ = "memberships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    body: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'posts.body'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Sponsor(Base):
    __tablename__ = "sponsors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sponsor_user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    sponsee_user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str | None] = mapped_column(String(255), nullable=True)

class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schedule: Mapped[dict | None] = mapped_column(JSON, default=dict)
    location_or_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSON, default=dict)

class Attendance(Base):
    __tablename__ = "attendances"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    meeting_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("meetings.id", ondelete="CASCADE"), index=True, nullable=True)
    attended_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Chip(Base):
    __tablename__ = "chips"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    milestone_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awarded_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    body: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'journal_entries.body'), nullable=True)
    mood: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'journal_entries.mood'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    private: Mapped[bool | None] = mapped_column(Boolean, default=False)

class Milestone(Base):
    __tablename__ = "milestones"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reached_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
