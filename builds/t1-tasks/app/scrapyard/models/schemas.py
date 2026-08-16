"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    user_id: int | None = None
    name: str | None = None
    status: str | None = None

class ProjectUpdate(BaseModel):
    user_id: int | None = None
    name: str | None = None
    status: str | None = None

class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    name: str | None = None
    status: str | None = None

class TaskCreate(BaseModel):
    user_id: int | None = None
    project_id: int | None = None
    title: str | None = None
    notes: str | None = None
    priority: str | None = None
    due_at: int | None = None
    status: str | None = None

class TaskUpdate(BaseModel):
    user_id: int | None = None
    project_id: int | None = None
    title: str | None = None
    notes: str | None = None
    priority: str | None = None
    due_at: int | None = None
    status: str | None = None

class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    project_id: int | None = None
    title: str | None = None
    notes: str | None = None
    priority: str | None = None
    due_at: int | None = None
    status: str | None = None

class LabelCreate(BaseModel):
    name: str | None = None

class LabelUpdate(BaseModel):
    name: str | None = None

class LabelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
