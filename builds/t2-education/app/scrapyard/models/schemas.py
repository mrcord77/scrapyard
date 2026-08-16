"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CourseCreate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    price_cents: int | None = None

class CourseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    price_cents: int | None = None

class CourseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str | None = None
    description: str | None = None
    status: str | None = None
    price_cents: int | None = None

class ModuleCreate(BaseModel):
    course_id: int | None = None
    title: str | None = None
    order: int | None = None

class ModuleUpdate(BaseModel):
    course_id: int | None = None
    title: str | None = None
    order: int | None = None

class ModuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    course_id: int | None = None
    title: str | None = None
    order: int | None = None

class LessonCreate(BaseModel):
    module_id: int | None = None
    title: str | None = None
    content: str | None = None
    media_id: int | None = None
    order: int | None = None

class LessonUpdate(BaseModel):
    module_id: int | None = None
    title: str | None = None
    content: str | None = None
    media_id: int | None = None
    order: int | None = None

class LessonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    module_id: int | None = None
    title: str | None = None
    content: str | None = None
    media_id: int | None = None
    order: int | None = None

class EnrollmentCreate(BaseModel):
    user_id: int | None = None
    course_id: int | None = None
    status: str | None = None
    enrolled_at: datetime | None = None

class EnrollmentUpdate(BaseModel):
    user_id: int | None = None
    course_id: int | None = None
    status: str | None = None
    enrolled_at: datetime | None = None

class EnrollmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    course_id: int | None = None
    status: str | None = None
    enrolled_at: datetime | None = None

class ProgressCreate(BaseModel):
    enrollment_id: int | None = None
    lesson_id: int | None = None
    completed_at: datetime | None = None

class ProgressUpdate(BaseModel):
    enrollment_id: int | None = None
    lesson_id: int | None = None
    completed_at: datetime | None = None

class ProgressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    enrollment_id: int | None = None
    lesson_id: int | None = None
    completed_at: datetime | None = None
