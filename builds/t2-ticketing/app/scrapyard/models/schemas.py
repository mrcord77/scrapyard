"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    name: str | None = None
    client: str | None = None
    status: str | None = None
    budget_cents: int | None = None

class ProjectUpdate(BaseModel):
    name: str | None = None
    client: str | None = None
    status: str | None = None
    budget_cents: int | None = None

class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
    client: str | None = None
    status: str | None = None
    budget_cents: int | None = None

class TaskCreate(BaseModel):
    project_id: int | None = None
    title: str | None = None
    assignee_id: int | None = None
    status: str | None = None
    due: datetime | None = None

class TaskUpdate(BaseModel):
    project_id: int | None = None
    title: str | None = None
    assignee_id: int | None = None
    status: str | None = None
    due: datetime | None = None

class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int | None = None
    title: str | None = None
    assignee_id: int | None = None
    status: str | None = None
    due: datetime | None = None

class ChangeOrderCreate(BaseModel):
    project_id: int | None = None
    amount_cents: int | None = None
    status: str | None = None
    reason: str | None = None

class ChangeOrderUpdate(BaseModel):
    project_id: int | None = None
    amount_cents: int | None = None
    status: str | None = None
    reason: str | None = None

class ChangeOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int | None = None
    amount_cents: int | None = None
    status: str | None = None
    reason: str | None = None

class DocumentCreate(BaseModel):
    project_id: int | None = None
    kind: str | None = None
    media_id: int | None = None
    uploaded_at: datetime | None = None

class DocumentUpdate(BaseModel):
    project_id: int | None = None
    kind: str | None = None
    media_id: int | None = None
    uploaded_at: datetime | None = None

class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int | None = None
    kind: str | None = None
    media_id: int | None = None
    uploaded_at: datetime | None = None
