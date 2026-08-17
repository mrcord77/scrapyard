"""Generated SQLAlchemy models. Do not hand-edit; regenerate from the domain."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Integer, String, Text, Boolean, DateTime, Float, JSON, func, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from scrapyard.security.pq_field_encryption import PQEncryptedString  # hybrid PQ encryption at rest


class Base(DeclarativeBase):
    pass


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    insurer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claim_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'claims.service'), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    billed_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="submitted", index=True)

class Denial(Base):
    __tablename__ = "denials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    claim_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("claims.id", ondelete="CASCADE"), index=True, nullable=True)
    denial_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason_text: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'denials.reason_text'), nullable=True)
    internal_appeal_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_review_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Appeal(Base):
    __tablename__ = "appeals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    claim_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("claims.id", ondelete="CASCADE"), index=True, nullable=True)
    level: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    argument: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'appeals.argument'), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="drafting", index=True)

class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    claim_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("claims.id", ondelete="CASCADE"), index=True, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'evidence_items.body'), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class CallLog(Base):
    __tablename__ = "call_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    claim_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("claims.id", ondelete="CASCADE"), index=True, nullable=True)
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rep_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(PQEncryptedString(aad=b'call_logs.summary'), nullable=True)
