"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    display_name: str | None = None
    email: str | None = None

class UserUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None

class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    display_name: str | None = None
    email: str | None = None
    created_at: datetime | None = None

class MembershipCreate(BaseModel):
    user_id: int | None = None
    role: str | None = None
    joined_at: datetime | None = None

class MembershipUpdate(BaseModel):
    user_id: int | None = None
    role: str | None = None
    joined_at: datetime | None = None

class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    role: str | None = None
    joined_at: datetime | None = None

class PostCreate(BaseModel):
    user_id: int | None = None
    body: str | None = None

class PostUpdate(BaseModel):
    user_id: int | None = None
    body: str | None = None

class PostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    body: str | None = None
    created_at: datetime | None = None
