"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class TenancyCreate(BaseModel):
    user_id: int | None = None
    address: str | None = None
    landlord: str | None = None
    deposit_cents: int | None = None
    move_in: datetime | None = None
    move_out: datetime | None = None
    return_deadline_days: int | None = None
    status: str | None = None

class TenancyUpdate(BaseModel):
    user_id: int | None = None
    address: str | None = None
    landlord: str | None = None
    deposit_cents: int | None = None
    move_in: datetime | None = None
    move_out: datetime | None = None
    return_deadline_days: int | None = None
    status: str | None = None

class TenancyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    address: str | None = None
    landlord: str | None = None
    deposit_cents: int | None = None
    move_in: datetime | None = None
    move_out: datetime | None = None
    return_deadline_days: int | None = None
    status: str | None = None

class EvidenceShotCreate(BaseModel):
    user_id: int | None = None
    tenancy_id: int | None = None
    phase: str | None = None
    room: str | None = None
    photo_ref: str | None = None
    condition_note: str | None = None
    taken_at: datetime | None = None

class EvidenceShotUpdate(BaseModel):
    user_id: int | None = None
    tenancy_id: int | None = None
    phase: str | None = None
    room: str | None = None
    photo_ref: str | None = None
    condition_note: str | None = None
    taken_at: datetime | None = None

class EvidenceShotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    tenancy_id: int | None = None
    phase: str | None = None
    room: str | None = None
    photo_ref: str | None = None
    condition_note: str | None = None
    taken_at: datetime | None = None

class DeductionCreate(BaseModel):
    user_id: int | None = None
    tenancy_id: int | None = None
    amount_cents: int | None = None
    landlord_reason: str | None = None
    status: str | None = None

class DeductionUpdate(BaseModel):
    user_id: int | None = None
    tenancy_id: int | None = None
    amount_cents: int | None = None
    landlord_reason: str | None = None
    status: str | None = None

class DeductionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    tenancy_id: int | None = None
    amount_cents: int | None = None
    landlord_reason: str | None = None
    status: str | None = None

class DisputeLetterCreate(BaseModel):
    user_id: int | None = None
    tenancy_id: int | None = None
    sent_at: datetime | None = None
    method: str | None = None
    body: str | None = None

class DisputeLetterUpdate(BaseModel):
    user_id: int | None = None
    tenancy_id: int | None = None
    sent_at: datetime | None = None
    method: str | None = None
    body: str | None = None

class DisputeLetterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    tenancy_id: int | None = None
    sent_at: datetime | None = None
    method: str | None = None
    body: str | None = None
