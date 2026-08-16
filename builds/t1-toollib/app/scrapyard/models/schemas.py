"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class MemberCreate(BaseModel):
    name: str | None = None
    status: str | None = None

class MemberUpdate(BaseModel):
    name: str | None = None
    status: str | None = None

class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
    status: str | None = None

class ToolCreate(BaseModel):
    name: str | None = None
    status: str | None = None

class ToolUpdate(BaseModel):
    name: str | None = None
    status: str | None = None

class ToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
    status: str | None = None

class ReservationCreate(BaseModel):
    member_id: int | None = None
    tool_id: int | None = None
    start_at: int | None = None
    end_at: int | None = None
    status: str | None = None

class ReservationUpdate(BaseModel):
    member_id: int | None = None
    tool_id: int | None = None
    start_at: int | None = None
    end_at: int | None = None
    status: str | None = None

class ReservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    member_id: int | None = None
    tool_id: int | None = None
    start_at: int | None = None
    end_at: int | None = None
    status: str | None = None

class IncidentCreate(BaseModel):
    tool_id: int | None = None
    reservation_id: int | None = None
    note: str | None = None

class IncidentUpdate(BaseModel):
    tool_id: int | None = None
    reservation_id: int | None = None
    note: str | None = None

class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tool_id: int | None = None
    reservation_id: int | None = None
    note: str | None = None

class MaintenanceRecordCreate(BaseModel):
    tool_id: int | None = None
    status: str | None = None
    resolution: str | None = None

class MaintenanceRecordUpdate(BaseModel):
    tool_id: int | None = None
    status: str | None = None
    resolution: str | None = None

class MaintenanceRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tool_id: int | None = None
    status: str | None = None
    resolution: str | None = None

class TagCreate(BaseModel):
    name: str | None = None

class TagUpdate(BaseModel):
    name: str | None = None

class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
