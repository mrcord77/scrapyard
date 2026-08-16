"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import WellCreate, WellUpdate, WellRead, LeaseCreate, LeaseUpdate, LeaseRead, ProductionLogCreate, ProductionLogUpdate, ProductionLogRead, WorkOrderCreate, WorkOrderUpdate, WorkOrderRead
from .services import WellService, LeaseService, ProductionLogService, WorkOrderService
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

# --- Well ---
@router.get("/wells", response_model=list[WellRead])
def list_wells(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return WellService(db).list(limit=limit, offset=offset)

@router.get("/wells/{id_}", response_model=WellRead)
def get_well(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = WellService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/wells", response_model=WellRead, status_code=201)
def create_well(payload: WellCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = WellService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/wells/{id_}", response_model=WellRead)
def update_well(id_: int, payload: WellUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = WellService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/wells/{id_}", status_code=204)
def delete_well(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not WellService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Lease ---
@router.get("/leases", response_model=list[LeaseRead])
def list_leases(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return LeaseService(db).list(limit=limit, offset=offset)

@router.get("/leases/{id_}", response_model=LeaseRead)
def get_lease(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LeaseService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/leases", response_model=LeaseRead, status_code=201)
def create_lease(payload: LeaseCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LeaseService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/leases/{id_}", response_model=LeaseRead)
def update_lease(id_: int, payload: LeaseUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LeaseService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/leases/{id_}", status_code=204)
def delete_lease(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not LeaseService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- ProductionLog ---
@router.get("/production_logs", response_model=list[ProductionLogRead])
def list_production_logs(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return ProductionLogService(db).list(limit=limit, offset=offset)

@router.get("/production_logs/{id_}", response_model=ProductionLogRead)
def get_production_log(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProductionLogService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/production_logs", response_model=ProductionLogRead, status_code=201)
def create_production_log(payload: ProductionLogCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProductionLogService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/production_logs/{id_}", response_model=ProductionLogRead)
def update_production_log(id_: int, payload: ProductionLogUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProductionLogService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/production_logs/{id_}", status_code=204)
def delete_production_log(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not ProductionLogService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- WorkOrder ---
@router.get("/work_orders", response_model=list[WorkOrderRead])
def list_work_orders(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return WorkOrderService(db).list(limit=limit, offset=offset)

@router.get("/work_orders/{id_}", response_model=WorkOrderRead)
def get_work_order(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = WorkOrderService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/work_orders", response_model=WorkOrderRead, status_code=201)
def create_work_order(payload: WorkOrderCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = WorkOrderService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/work_orders/{id_}", response_model=WorkOrderRead)
def update_work_order(id_: int, payload: WorkOrderUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = WorkOrderService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/work_orders/{id_}", status_code=204)
def delete_work_order(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not WorkOrderService(db).delete(id_): raise HTTPException(404)
    db.commit()
