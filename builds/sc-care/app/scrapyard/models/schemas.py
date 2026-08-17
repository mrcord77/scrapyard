"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CareRecipientCreate(BaseModel):
    name: str | None = None
    lives_at: str | None = None
    primary_doctor: str | None = None
    emergency_contact: str | None = None

class CareRecipientUpdate(BaseModel):
    name: str | None = None
    lives_at: str | None = None
    primary_doctor: str | None = None
    emergency_contact: str | None = None

class CareRecipientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
    lives_at: str | None = None
    primary_doctor: str | None = None
    emergency_contact: str | None = None

class CareTaskCreate(BaseModel):
    recipient_id: int | None = None
    title: str | None = None
    assigned_to: str | None = None
    due_at: datetime | None = None
    status: str | None = None

class CareTaskUpdate(BaseModel):
    recipient_id: int | None = None
    title: str | None = None
    assigned_to: str | None = None
    due_at: datetime | None = None
    status: str | None = None

class CareTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    recipient_id: int | None = None
    title: str | None = None
    assigned_to: str | None = None
    due_at: datetime | None = None
    status: str | None = None

class MedicationCreate(BaseModel):
    recipient_id: int | None = None
    name: str | None = None
    dose: str | None = None
    schedule: str | None = None
    prescriber: str | None = None
    status: str | None = None

class MedicationUpdate(BaseModel):
    recipient_id: int | None = None
    name: str | None = None
    dose: str | None = None
    schedule: str | None = None
    prescriber: str | None = None
    status: str | None = None

class MedicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    recipient_id: int | None = None
    name: str | None = None
    dose: str | None = None
    schedule: str | None = None
    prescriber: str | None = None
    status: str | None = None

class DoseLogCreate(BaseModel):
    medication_id: int | None = None
    given_at: datetime | None = None
    given_by: str | None = None
    taken: bool | None = None
    note: str | None = None

class DoseLogUpdate(BaseModel):
    medication_id: int | None = None
    given_at: datetime | None = None
    given_by: str | None = None
    taken: bool | None = None
    note: str | None = None

class DoseLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    medication_id: int | None = None
    given_at: datetime | None = None
    given_by: str | None = None
    taken: bool | None = None
    note: str | None = None

class AppointmentCreate(BaseModel):
    recipient_id: int | None = None
    with_whom: str | None = None
    at: datetime | None = None
    driver: str | None = None
    outcome_note: str | None = None
    status: str | None = None

class AppointmentUpdate(BaseModel):
    recipient_id: int | None = None
    with_whom: str | None = None
    at: datetime | None = None
    driver: str | None = None
    outcome_note: str | None = None
    status: str | None = None

class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    recipient_id: int | None = None
    with_whom: str | None = None
    at: datetime | None = None
    driver: str | None = None
    outcome_note: str | None = None
    status: str | None = None

class UpdateCreate(BaseModel):
    recipient_id: int | None = None
    author: str | None = None
    posted_at: datetime | None = None
    body: str | None = None

class UpdateUpdate(BaseModel):
    recipient_id: int | None = None
    author: str | None = None
    posted_at: datetime | None = None
    body: str | None = None

class UpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    recipient_id: int | None = None
    author: str | None = None
    posted_at: datetime | None = None
    body: str | None = None
