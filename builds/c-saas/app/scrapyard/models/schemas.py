"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class AccountCreate(BaseModel):
    name: str | None = None
    plan_id: int | None = None
    status: str | None = None

class AccountUpdate(BaseModel):
    name: str | None = None
    plan_id: int | None = None
    status: str | None = None

class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
    plan_id: int | None = None
    status: str | None = None
    created_at: datetime | None = None

class MemberCreate(BaseModel):
    account_id: int | None = None
    user_id: int | None = None
    role: str | None = None
    invited_at: datetime | None = None

class MemberUpdate(BaseModel):
    account_id: int | None = None
    user_id: int | None = None
    role: str | None = None
    invited_at: datetime | None = None

class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int | None = None
    user_id: int | None = None
    role: str | None = None
    invited_at: datetime | None = None

class PlanCreate(BaseModel):
    name: str | None = None
    price_cents: int | None = None
    interval: str | None = None
    entitlements: dict | None = None

class PlanUpdate(BaseModel):
    name: str | None = None
    price_cents: int | None = None
    interval: str | None = None
    entitlements: dict | None = None

class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
    price_cents: int | None = None
    interval: str | None = None
    entitlements: dict | None = None

class InvitationCreate(BaseModel):
    account_id: int | None = None
    email: str | None = None
    role: str | None = None
    token: str | None = None
    expires_at: datetime | None = None

class InvitationUpdate(BaseModel):
    account_id: int | None = None
    email: str | None = None
    role: str | None = None
    token: str | None = None
    expires_at: datetime | None = None

class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int | None = None
    email: str | None = None
    role: str | None = None
    token: str | None = None
    expires_at: datetime | None = None
