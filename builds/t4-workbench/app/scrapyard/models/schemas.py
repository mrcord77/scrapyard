"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ResearchDocCreate(BaseModel):
    user_id: int | None = None
    title: str | None = None
    source_url: str | None = None
    content: str | None = None
    status: str | None = None

class ResearchDocUpdate(BaseModel):
    user_id: int | None = None
    title: str | None = None
    source_url: str | None = None
    content: str | None = None
    status: str | None = None

class ResearchDocRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    title: str | None = None
    source_url: str | None = None
    content: str | None = None
    status: str | None = None

class NoteCreate(BaseModel):
    user_id: int | None = None
    doc_id: int | None = None
    body: str | None = None
    kind: str | None = None

class NoteUpdate(BaseModel):
    user_id: int | None = None
    doc_id: int | None = None
    body: str | None = None
    kind: str | None = None

class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    doc_id: int | None = None
    body: str | None = None
    kind: str | None = None

class ExperimentCreate(BaseModel):
    user_id: int | None = None
    name: str | None = None
    hypothesis: str | None = None
    status: str | None = None

class ExperimentUpdate(BaseModel):
    user_id: int | None = None
    name: str | None = None
    hypothesis: str | None = None
    status: str | None = None

class ExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    name: str | None = None
    hypothesis: str | None = None
    status: str | None = None

class RunCreate(BaseModel):
    user_id: int | None = None
    experiment_id: int | None = None
    params: dict | None = None
    metrics: dict | None = None
    status: str | None = None

class RunUpdate(BaseModel):
    user_id: int | None = None
    experiment_id: int | None = None
    params: dict | None = None
    metrics: dict | None = None
    status: str | None = None

class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    experiment_id: int | None = None
    params: dict | None = None
    metrics: dict | None = None
    status: str | None = None

class TagCreate(BaseModel):
    name: str | None = None

class TagUpdate(BaseModel):
    name: str | None = None

class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
