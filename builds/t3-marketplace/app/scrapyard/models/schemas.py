"""Generated Pydantic v2 schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ProductCreate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    tags: dict | None = None

class ProductUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    tags: dict | None = None

class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str | None = None
    description: str | None = None
    status: str | None = None
    tags: dict | None = None

class VariantCreate(BaseModel):
    product_id: int | None = None
    sku: str | None = None
    price_cents: int | None = None
    inventory_qty: int | None = None

class VariantUpdate(BaseModel):
    product_id: int | None = None
    sku: str | None = None
    price_cents: int | None = None
    inventory_qty: int | None = None

class VariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int | None = None
    sku: str | None = None
    price_cents: int | None = None
    inventory_qty: int | None = None

class CartCreate(BaseModel):
    user_id: int | None = None
    items: dict | None = None

class CartUpdate(BaseModel):
    user_id: int | None = None
    items: dict | None = None

class CartRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    items: dict | None = None
    updated_at: datetime | None = None

class OrderCreate(BaseModel):
    user_id: int | None = None
    status: str | None = None
    total_cents: int | None = None
    placed_at: datetime | None = None

class OrderUpdate(BaseModel):
    user_id: int | None = None
    status: str | None = None
    total_cents: int | None = None
    placed_at: datetime | None = None

class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    status: str | None = None
    total_cents: int | None = None
    placed_at: datetime | None = None

class ShipmentCreate(BaseModel):
    order_id: int | None = None
    carrier: str | None = None
    tracking: str | None = None
    status: str | None = None

class ShipmentUpdate(BaseModel):
    order_id: int | None = None
    carrier: str | None = None
    tracking: str | None = None
    status: str | None = None

class ShipmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int | None = None
    carrier: str | None = None
    tracking: str | None = None
    status: str | None = None
