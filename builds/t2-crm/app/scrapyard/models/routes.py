"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import LeadCreate, LeadUpdate, LeadRead
from .services import LeadService
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

# --- Lead ---
@router.get("/leads", response_model=list[LeadRead])
def list_leads(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return LeadService(db).list(limit=limit, offset=offset)

@router.get("/leads/{id_}", response_model=LeadRead)
def get_lead(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LeadService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/leads", response_model=LeadRead, status_code=201)
def create_lead(payload: LeadCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LeadService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/leads/{id_}", response_model=LeadRead)
def update_lead(id_: int, payload: LeadUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LeadService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/leads/{id_}", status_code=204)
def delete_lead(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not LeadService(db).delete(id_): raise HTTPException(404)
    db.commit()
