"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ListingCreate(BaseModel):
    address: str | None = None
    price_cents: int | None = None
    status: str | None = None
    beds: int | None = None
    baths: int | None = None
    sqft: int | None = None
    agent_id: int | None = None

class ListingUpdate(BaseModel):
    address: str | None = None
    price_cents: int | None = None
    status: str | None = None
    beds: int | None = None
    baths: int | None = None
    sqft: int | None = None
    agent_id: int | None = None

class ListingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    address: str | None = None
    price_cents: int | None = None
    status: str | None = None
    beds: int | None = None
    baths: int | None = None
    sqft: int | None = None
    agent_id: int | None = None

class AgentCreate(BaseModel):
    user_id: int | None = None
    license_no: int | None = None
    brokerage: str | None = None

class AgentUpdate(BaseModel):
    user_id: int | None = None
    license_no: int | None = None
    brokerage: str | None = None

class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    license_no: int | None = None
    brokerage: str | None = None

class ShowingCreate(BaseModel):
    listing_id: int | None = None
    client_id: int | None = None
    scheduled_at: datetime | None = None
    status: str | None = None

class ShowingUpdate(BaseModel):
    listing_id: int | None = None
    client_id: int | None = None
    scheduled_at: datetime | None = None
    status: str | None = None

class ShowingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    listing_id: int | None = None
    client_id: int | None = None
    scheduled_at: datetime | None = None
    status: str | None = None

class InquiryCreate(BaseModel):
    listing_id: int | None = None
    name: str | None = None
    contact: str | None = None
    message: str | None = None

class InquiryUpdate(BaseModel):
    listing_id: int | None = None
    name: str | None = None
    contact: str | None = None
    message: str | None = None

class InquiryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    listing_id: int | None = None
    name: str | None = None
    contact: str | None = None
    message: str | None = None
    created_at: datetime | None = None
