"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    email: str | None = None

class UserUpdate(BaseModel):
    email: str | None = None

class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str | None = None

class RepairTicketCreate(BaseModel):
    user_id: int | None = None
    bike_model: str | None = None
    parts_received: bool | None = None
    paid: bool | None = None
    status: str | None = None

class RepairTicketUpdate(BaseModel):
    user_id: int | None = None
    bike_model: str | None = None
    parts_received: bool | None = None
    paid: bool | None = None
    status: str | None = None

class RepairTicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    bike_model: str | None = None
    parts_received: bool | None = None
    paid: bool | None = None
    status: str | None = None
