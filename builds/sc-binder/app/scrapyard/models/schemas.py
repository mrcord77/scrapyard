"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ChildCreate(BaseModel):
    user_id: int | None = None
    first_name: str | None = None
    grade: str | None = None
    school: str | None = None
    plan_type: str | None = None
    diagnosis: str | None = None
    notes: str | None = None
    promised_minutes_week: int | None = None

class ChildUpdate(BaseModel):
    user_id: int | None = None
    first_name: str | None = None
    grade: str | None = None
    school: str | None = None
    plan_type: str | None = None
    diagnosis: str | None = None
    notes: str | None = None
    promised_minutes_week: int | None = None

class ChildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    first_name: str | None = None
    grade: str | None = None
    school: str | None = None
    plan_type: str | None = None
    diagnosis: str | None = None
    notes: str | None = None
    promised_minutes_week: int | None = None

class MeetingCreate(BaseModel):
    user_id: int | None = None
    child_id: int | None = None
    kind: str | None = None
    held_at: datetime | None = None
    attendees: str | None = None
    notes: str | None = None
    status: str | None = None

class MeetingUpdate(BaseModel):
    user_id: int | None = None
    child_id: int | None = None
    kind: str | None = None
    held_at: datetime | None = None
    attendees: str | None = None
    notes: str | None = None
    status: str | None = None

class MeetingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    child_id: int | None = None
    kind: str | None = None
    held_at: datetime | None = None
    attendees: str | None = None
    notes: str | None = None
    status: str | None = None

class CorrespondenceCreate(BaseModel):
    user_id: int | None = None
    child_id: int | None = None
    direction: str | None = None
    with_whom: str | None = None
    channel: str | None = None
    sent_at: datetime | None = None
    subject: str | None = None
    body: str | None = None

class CorrespondenceUpdate(BaseModel):
    user_id: int | None = None
    child_id: int | None = None
    direction: str | None = None
    with_whom: str | None = None
    channel: str | None = None
    sent_at: datetime | None = None
    subject: str | None = None
    body: str | None = None

class CorrespondenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    child_id: int | None = None
    direction: str | None = None
    with_whom: str | None = None
    channel: str | None = None
    sent_at: datetime | None = None
    subject: str | None = None
    body: str | None = None

class ServiceEntryCreate(BaseModel):
    user_id: int | None = None
    child_id: int | None = None
    service: str | None = None
    minutes: int | None = None
    delivered_at: datetime | None = None
    delivered: bool | None = None

class ServiceEntryUpdate(BaseModel):
    user_id: int | None = None
    child_id: int | None = None
    service: str | None = None
    minutes: int | None = None
    delivered_at: datetime | None = None
    delivered: bool | None = None

class ServiceEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    child_id: int | None = None
    service: str | None = None
    minutes: int | None = None
    delivered_at: datetime | None = None
    delivered: bool | None = None

class ActionItemCreate(BaseModel):
    user_id: int | None = None
    child_id: int | None = None
    owner: str | None = None
    description: str | None = None
    due_at: datetime | None = None
    status: str | None = None

class ActionItemUpdate(BaseModel):
    user_id: int | None = None
    child_id: int | None = None
    owner: str | None = None
    description: str | None = None
    due_at: datetime | None = None
    status: str | None = None

class ActionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    child_id: int | None = None
    owner: str | None = None
    description: str | None = None
    due_at: datetime | None = None
    status: str | None = None
