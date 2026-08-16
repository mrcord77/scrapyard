"""Generated SQLAlchemy models. Do not hand-edit; regenerate from the domain."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Integer, String, Text, Boolean, DateTime, Float, JSON, func, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Well(Base):
    __tablename__ = "wells"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("leases.id", ondelete="CASCADE"), index=True, nullable=True)
    status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[dict | None] = mapped_column(JSON, default=dict)

class Lease(Base):
    __tablename__ = "leases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    county: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str | None] = mapped_column(String(255), nullable=True)

class ProductionLog(Base):
    __tablename__ = "production_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    well_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("wells.id", ondelete="CASCADE"), index=True, nullable=True)
    date: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oil_bbl: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gas_mcf: Mapped[int | None] = mapped_column(Integer, nullable=True)
    water_bbl: Mapped[int | None] = mapped_column(Integer, nullable=True)

class WorkOrder(Base):
    __tablename__ = "work_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    well_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("wells.id", ondelete="CASCADE"), index=True, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
