"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import ListingCreate, ListingUpdate, ListingRead, AgentCreate, AgentUpdate, AgentRead, ShowingCreate, ShowingUpdate, ShowingRead, InquiryCreate, InquiryUpdate, InquiryRead
from .services import ListingService, AgentService, ShowingService, InquiryService
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

# --- Listing ---
@router.get("/listings", response_model=list[ListingRead])
def list_listings(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return ListingService(db).list(limit=limit, offset=offset)

@router.get("/listings/{id_}", response_model=ListingRead)
def get_listing(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ListingService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/listings", response_model=ListingRead, status_code=201)
def create_listing(payload: ListingCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ListingService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/listings/{id_}", response_model=ListingRead)
def update_listing(id_: int, payload: ListingUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ListingService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/listings/{id_}", status_code=204)
def delete_listing(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not ListingService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Agent ---
@router.get("/agents", response_model=list[AgentRead])
def list_agents(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return AgentService(db).list(limit=limit, offset=offset)

@router.get("/agents/{id_}", response_model=AgentRead)
def get_agent(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AgentService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/agents", response_model=AgentRead, status_code=201)
def create_agent(payload: AgentCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AgentService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/agents/{id_}", response_model=AgentRead)
def update_agent(id_: int, payload: AgentUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AgentService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/agents/{id_}", status_code=204)
def delete_agent(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not AgentService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Showing ---
@router.get("/showings", response_model=list[ShowingRead])
def list_showings(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return ShowingService(db).list(limit=limit, offset=offset)

@router.get("/showings/{id_}", response_model=ShowingRead)
def get_showing(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ShowingService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/showings", response_model=ShowingRead, status_code=201)
def create_showing(payload: ShowingCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ShowingService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/showings/{id_}", response_model=ShowingRead)
def update_showing(id_: int, payload: ShowingUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ShowingService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/showings/{id_}", status_code=204)
def delete_showing(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not ShowingService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Inquiry ---
@router.get("/inquiries", response_model=list[InquiryRead])
def list_inquiries(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return InquiryService(db).list(limit=limit, offset=offset)

@router.get("/inquiries/{id_}", response_model=InquiryRead)
def get_inquiry(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = InquiryService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/inquiries", response_model=InquiryRead, status_code=201)
def create_inquiry(payload: InquiryCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = InquiryService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/inquiries/{id_}", response_model=InquiryRead)
def update_inquiry(id_: int, payload: InquiryUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = InquiryService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/inquiries/{id_}", status_code=204)
def delete_inquiry(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not InquiryService(db).delete(id_): raise HTTPException(404)
    db.commit()
