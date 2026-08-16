"""Generated SQLAlchemy models. Do not hand-edit; regenerate from the domain."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Integer, String, Text, Boolean, DateTime, Float, JSON, func, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

class Module(Base):
    __tablename__ = "modules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order: Mapped[int | None] = mapped_column(Integer, nullable=True)

class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("modules.id", ondelete="CASCADE"), index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    order: Mapped[int | None] = mapped_column(Integer, nullable=True)

class Enrollment(Base):
    __tablename__ = "enrollments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    course_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=True)
    status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Progress(Base):
    __tablename__ = "progresses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enrollment_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("enrollments.id", ondelete="CASCADE"), index=True, nullable=True)
    lesson_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("lessons.id", ondelete="CASCADE"), index=True, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
