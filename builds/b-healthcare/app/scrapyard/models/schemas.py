"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class PatientCreate(BaseModel):
    user_id: int | None = None
    dob: datetime | None = None
    mrn: str | None = None

class PatientUpdate(BaseModel):
    user_id: int | None = None
    dob: datetime | None = None
    mrn: str | None = None

class PatientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    dob: datetime | None = None
    mrn: str | None = None

class ProviderCreate(BaseModel):
    user_id: int | None = None
    npi: str | None = None
    specialty: str | None = None

class ProviderUpdate(BaseModel):
    user_id: int | None = None
    npi: str | None = None
    specialty: str | None = None

class ProviderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    npi: str | None = None
    specialty: str | None = None

class AppointmentCreate(BaseModel):
    patient_id: int | None = None
    provider_id: int | None = None
    starts_at: datetime | None = None
    status: str | None = None

class AppointmentUpdate(BaseModel):
    patient_id: int | None = None
    provider_id: int | None = None
    starts_at: datetime | None = None
    status: str | None = None

class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    patient_id: int | None = None
    provider_id: int | None = None
    starts_at: datetime | None = None
    status: str | None = None

class EncounterCreate(BaseModel):
    appointment_id: int | None = None
    notes_ref: str | None = None

class EncounterUpdate(BaseModel):
    appointment_id: int | None = None
    notes_ref: str | None = None

class EncounterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    appointment_id: int | None = None
    notes_ref: str | None = None
    created_at: datetime | None = None
