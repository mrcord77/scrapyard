"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class WellCreate(BaseModel):
    name: str | None = None
    lease_id: int | None = None
    status: str | None = None
    location: dict | None = None

class WellUpdate(BaseModel):
    name: str | None = None
    lease_id: int | None = None
    status: str | None = None
    location: dict | None = None

class WellRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
    lease_id: int | None = None
    status: str | None = None
    location: dict | None = None

class LeaseCreate(BaseModel):
    name: str | None = None
    operator: str | None = None
    county: str | None = None
    state: str | None = None

class LeaseUpdate(BaseModel):
    name: str | None = None
    operator: str | None = None
    county: str | None = None
    state: str | None = None

class LeaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
    operator: str | None = None
    county: str | None = None
    state: str | None = None

class ProductionLogCreate(BaseModel):
    well_id: int | None = None
    date: str | None = None
    oil_bbl: int | None = None
    gas_mcf: int | None = None
    water_bbl: int | None = None

class ProductionLogUpdate(BaseModel):
    well_id: int | None = None
    date: str | None = None
    oil_bbl: int | None = None
    gas_mcf: int | None = None
    water_bbl: int | None = None

class ProductionLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    well_id: int | None = None
    date: str | None = None
    oil_bbl: int | None = None
    gas_mcf: int | None = None
    water_bbl: int | None = None

class WorkOrderCreate(BaseModel):
    well_id: int | None = None
    kind: str | None = None
    status: str | None = None
    scheduled_at: datetime | None = None

class WorkOrderUpdate(BaseModel):
    well_id: int | None = None
    kind: str | None = None
    status: str | None = None
    scheduled_at: datetime | None = None

class WorkOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    well_id: int | None = None
    kind: str | None = None
    status: str | None = None
    scheduled_at: datetime | None = None
