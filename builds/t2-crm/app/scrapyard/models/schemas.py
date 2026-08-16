"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class LeadCreate(BaseModel):
    source: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    zip: str | None = None
    intent: str | None = None
    answers: dict | None = None
    estimate_lo: int | None = None
    estimate_hi: int | None = None
    message: str | None = None
    score: int | None = None
    verdict: str | None = None
    flags: dict | None = None
    gaps: dict | None = None
    draft_reply: str | None = None
    panel_risk: str | None = None
    status: str | None = None

class LeadUpdate(BaseModel):
    source: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    zip: str | None = None
    intent: str | None = None
    answers: dict | None = None
    estimate_lo: int | None = None
    estimate_hi: int | None = None
    message: str | None = None
    score: int | None = None
    verdict: str | None = None
    flags: dict | None = None
    gaps: dict | None = None
    draft_reply: str | None = None
    panel_risk: str | None = None
    status: str | None = None

class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    zip: str | None = None
    intent: str | None = None
    answers: dict | None = None
    estimate_lo: int | None = None
    estimate_hi: int | None = None
    message: str | None = None
    score: int | None = None
    verdict: str | None = None
    flags: dict | None = None
    gaps: dict | None = None
    draft_reply: str | None = None
    panel_risk: str | None = None
    status: str | None = None
    created_at: datetime | None = None
