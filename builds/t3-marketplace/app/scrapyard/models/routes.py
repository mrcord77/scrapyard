"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import ProductCreate, ProductUpdate, ProductRead, VariantCreate, VariantUpdate, VariantRead, CartCreate, CartUpdate, CartRead, OrderCreate, OrderUpdate, OrderRead, ShipmentCreate, ShipmentUpdate, ShipmentRead
from .services import ProductService, VariantService, CartService, OrderService, ShipmentService
from scrapyard.database.db_session import get_db  # wired to the real session factory
from fastapi import Header
from scrapyard.identity.session_manager import SessionManager

def current_user_id(x_session: str | None = Header(None, alias='X-Session'),
                    db: Session = Depends(get_db)) -> int:
    """Resolve the authenticated user from the X-Session header; 401 if absent/invalid."""
    uid = SessionManager(db).user_id_for(x_session) if x_session else None
    if not uid:
        raise HTTPException(401, 'authentication required')
    return uid

router = APIRouter()

# --- Product ---
@router.get("/products", response_model=list[ProductRead])
def list_products(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return ProductService(db).list(limit=limit, offset=offset)

@router.get("/products/{id_}", response_model=ProductRead)
def get_product(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProductService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/products", response_model=ProductRead, status_code=201)
def create_product(payload: ProductCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProductService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/products/{id_}", response_model=ProductRead)
def update_product(id_: int, payload: ProductUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProductService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/products/{id_}", status_code=204)
def delete_product(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not ProductService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Variant ---
@router.get("/variants", response_model=list[VariantRead])
def list_variants(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return VariantService(db).list(limit=limit, offset=offset)

@router.get("/variants/{id_}", response_model=VariantRead)
def get_variant(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = VariantService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/variants", response_model=VariantRead, status_code=201)
def create_variant(payload: VariantCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = VariantService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/variants/{id_}", response_model=VariantRead)
def update_variant(id_: int, payload: VariantUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = VariantService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/variants/{id_}", status_code=204)
def delete_variant(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not VariantService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Cart ---
@router.get("/carts", response_model=list[CartRead])
def list_carts(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return CartService(db).list(limit=limit, offset=offset)

@router.get("/carts/{id_}", response_model=CartRead)
def get_cart(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CartService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/carts", response_model=CartRead, status_code=201)
def create_cart(payload: CartCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CartService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/carts/{id_}", response_model=CartRead)
def update_cart(id_: int, payload: CartUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CartService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/carts/{id_}", status_code=204)
def delete_cart(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not CartService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Order ---
@router.get("/orders", response_model=list[OrderRead])
def list_orders(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return OrderService(db).list(limit=limit, offset=offset)

@router.get("/orders/{id_}", response_model=OrderRead)
def get_order(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = OrderService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/orders", response_model=OrderRead, status_code=201)
def create_order(payload: OrderCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = OrderService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/orders/{id_}", response_model=OrderRead)
def update_order(id_: int, payload: OrderUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = OrderService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/orders/{id_}", status_code=204)
def delete_order(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not OrderService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Shipment ---
@router.get("/shipments", response_model=list[ShipmentRead])
def list_shipments(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return ShipmentService(db).list(limit=limit, offset=offset)

@router.get("/shipments/{id_}", response_model=ShipmentRead)
def get_shipment(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ShipmentService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/shipments", response_model=ShipmentRead, status_code=201)
def create_shipment(payload: ShipmentCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ShipmentService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/shipments/{id_}", response_model=ShipmentRead)
def update_shipment(id_: int, payload: ShipmentUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ShipmentService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/shipments/{id_}", status_code=204)
def delete_shipment(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not ShipmentService(db).delete(id_): raise HTTPException(404)
    db.commit()
