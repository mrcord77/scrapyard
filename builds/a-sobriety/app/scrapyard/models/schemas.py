"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    display_name: str | None = None
    sobriety_date: str | None = None
    timezone: str | None = None
    is_anonymous: bool | None = None

class UserUpdate(BaseModel):
    display_name: str | None = None
    sobriety_date: str | None = None
    timezone: str | None = None
    is_anonymous: bool | None = None

class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    display_name: str | None = None
    sobriety_date: str | None = None
    timezone: str | None = None
    is_anonymous: bool | None = None

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

class SponsorCreate(BaseModel):
    sponsor_user_id: int | None = None
    sponsee_user_id: int | None = None
    since: datetime | None = None
    status: str | None = None

class SponsorUpdate(BaseModel):
    sponsor_user_id: int | None = None
    sponsee_user_id: int | None = None
    since: datetime | None = None
    status: str | None = None

class SponsorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sponsor_user_id: int | None = None
    sponsee_user_id: int | None = None
    since: datetime | None = None
    status: str | None = None

class MeetingCreate(BaseModel):
    title: str | None = None
    kind: str | None = None
    schedule: dict | None = None
    location_or_url: str | None = None
    tags: dict | None = None

class MeetingUpdate(BaseModel):
    title: str | None = None
    kind: str | None = None
    schedule: dict | None = None
    location_or_url: str | None = None
    tags: dict | None = None

class MeetingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str | None = None
    kind: str | None = None
    schedule: dict | None = None
    location_or_url: str | None = None
    tags: dict | None = None

class AttendanceCreate(BaseModel):
    user_id: int | None = None
    meeting_id: int | None = None
    attended_on: datetime | None = None

class AttendanceUpdate(BaseModel):
    user_id: int | None = None
    meeting_id: int | None = None
    attended_on: datetime | None = None

class AttendanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    meeting_id: int | None = None
    attended_on: datetime | None = None

class ChipCreate(BaseModel):
    user_id: int | None = None
    milestone_days: int | None = None
    awarded_on: datetime | None = None

class ChipUpdate(BaseModel):
    user_id: int | None = None
    milestone_days: int | None = None
    awarded_on: datetime | None = None

class ChipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    milestone_days: int | None = None
    awarded_on: datetime | None = None

class JournalEntryCreate(BaseModel):
    user_id: int | None = None
    body: str | None = None
    mood: str | None = None
    private: bool | None = None

class JournalEntryUpdate(BaseModel):
    user_id: int | None = None
    body: str | None = None
    mood: str | None = None
    private: bool | None = None

class JournalEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    body: str | None = None
    mood: str | None = None
    created_at: datetime | None = None
    private: bool | None = None

class MilestoneCreate(BaseModel):
    user_id: int | None = None
    kind: str | None = None
    reached_on: datetime | None = None

class MilestoneUpdate(BaseModel):
    user_id: int | None = None
    kind: str | None = None
    reached_on: datetime | None = None

class MilestoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    kind: str | None = None
    reached_on: datetime | None = None
