"""Generated SQLAlchemy models. Do not hand-edit; regenerate from the domain."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Integer, String, Text, Boolean, DateTime, Float, JSON, func, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "app_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

class RepairTicket(Base):
    __tablename__ = "repair_tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    bike_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parts_received: Mapped[bool | None] = mapped_column(Boolean, default=False)
    paid: Mapped[bool | None] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(50), default="intake", index=True)
