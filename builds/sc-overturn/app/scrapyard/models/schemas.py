"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ClaimCreate(BaseModel):
    user_id: int | None = None
    insurer: str | None = None
    claim_number: str | None = None
    service: str | None = None
    provider: str | None = None
    service_date: datetime | None = None
    billed_cents: int | None = None
    status: str | None = None

class ClaimUpdate(BaseModel):
    user_id: int | None = None
    insurer: str | None = None
    claim_number: str | None = None
    service: str | None = None
    provider: str | None = None
    service_date: datetime | None = None
    billed_cents: int | None = None
    status: str | None = None

class ClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    insurer: str | None = None
    claim_number: str | None = None
    service: str | None = None
    provider: str | None = None
    service_date: datetime | None = None
    billed_cents: int | None = None
    status: str | None = None

class DenialCreate(BaseModel):
    user_id: int | None = None
    claim_id: int | None = None
    denial_date: datetime | None = None
    reason_code: str | None = None
    reason_text: str | None = None
    internal_appeal_deadline: datetime | None = None
    external_review_deadline: datetime | None = None

class DenialUpdate(BaseModel):
    user_id: int | None = None
    claim_id: int | None = None
    denial_date: datetime | None = None
    reason_code: str | None = None
    reason_text: str | None = None
    internal_appeal_deadline: datetime | None = None
    external_review_deadline: datetime | None = None

class DenialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    claim_id: int | None = None
    denial_date: datetime | None = None
    reason_code: str | None = None
    reason_text: str | None = None
    internal_appeal_deadline: datetime | None = None
    external_review_deadline: datetime | None = None

class AppealCreate(BaseModel):
    user_id: int | None = None
    claim_id: int | None = None
    level: str | None = None
    filed_at: datetime | None = None
    argument: str | None = None
    status: str | None = None

class AppealUpdate(BaseModel):
    user_id: int | None = None
    claim_id: int | None = None
    level: str | None = None
    filed_at: datetime | None = None
    argument: str | None = None
    status: str | None = None

class AppealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    claim_id: int | None = None
    level: str | None = None
    filed_at: datetime | None = None
    argument: str | None = None
    status: str | None = None

class EvidenceItemCreate(BaseModel):
    user_id: int | None = None
    claim_id: int | None = None
    kind: str | None = None
    title: str | None = None
    body: str | None = None
    received_at: datetime | None = None

class EvidenceItemUpdate(BaseModel):
    user_id: int | None = None
    claim_id: int | None = None
    kind: str | None = None
    title: str | None = None
    body: str | None = None
    received_at: datetime | None = None

class EvidenceItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    claim_id: int | None = None
    kind: str | None = None
    title: str | None = None
    body: str | None = None
    received_at: datetime | None = None

class CallLogCreate(BaseModel):
    user_id: int | None = None
    claim_id: int | None = None
    called_at: datetime | None = None
    rep_name: str | None = None
    reference_number: str | None = None
    summary: str | None = None

class CallLogUpdate(BaseModel):
    user_id: int | None = None
    claim_id: int | None = None
    called_at: datetime | None = None
    rep_name: str | None = None
    reference_number: str | None = None
    summary: str | None = None

class CallLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    claim_id: int | None = None
    called_at: datetime | None = None
    rep_name: str | None = None
    reference_number: str | None = None
    summary: str | None = None
