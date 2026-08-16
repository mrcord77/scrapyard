"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import AccountCreate, AccountUpdate, AccountRead, MemberCreate, MemberUpdate, MemberRead, PlanCreate, PlanUpdate, PlanRead, InvitationCreate, InvitationUpdate, InvitationRead
from .services import AccountService, MemberService, PlanService, InvitationService
from scrapyard.database.db_session import get_db  # wired to the real session factory

router = APIRouter()

# --- Account ---
@router.get("/accounts", response_model=list[AccountRead])
def list_accounts(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return AccountService(db).list(limit=limit, offset=offset)

@router.get("/accounts/{id_}", response_model=AccountRead)
def get_account(id_: int, db: Session = Depends(get_db)):
    obj = AccountService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/accounts", response_model=AccountRead, status_code=201)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    obj = AccountService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/accounts/{id_}", response_model=AccountRead)
def update_account(id_: int, payload: AccountUpdate, db: Session = Depends(get_db)):
    obj = AccountService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/accounts/{id_}", status_code=204)
def delete_account(id_: int, db: Session = Depends(get_db)):
    if not AccountService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Member ---
@router.get("/members", response_model=list[MemberRead])
def list_members(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return MemberService(db).list(limit=limit, offset=offset)

@router.get("/members/{id_}", response_model=MemberRead)
def get_member(id_: int, db: Session = Depends(get_db)):
    obj = MemberService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/members", response_model=MemberRead, status_code=201)
def create_member(payload: MemberCreate, db: Session = Depends(get_db)):
    obj = MemberService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/members/{id_}", response_model=MemberRead)
def update_member(id_: int, payload: MemberUpdate, db: Session = Depends(get_db)):
    obj = MemberService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/members/{id_}", status_code=204)
def delete_member(id_: int, db: Session = Depends(get_db)):
    if not MemberService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Plan ---
@router.get("/plans", response_model=list[PlanRead])
def list_plans(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return PlanService(db).list(limit=limit, offset=offset)

@router.get("/plans/{id_}", response_model=PlanRead)
def get_plan(id_: int, db: Session = Depends(get_db)):
    obj = PlanService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/plans", response_model=PlanRead, status_code=201)
def create_plan(payload: PlanCreate, db: Session = Depends(get_db)):
    obj = PlanService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/plans/{id_}", response_model=PlanRead)
def update_plan(id_: int, payload: PlanUpdate, db: Session = Depends(get_db)):
    obj = PlanService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/plans/{id_}", status_code=204)
def delete_plan(id_: int, db: Session = Depends(get_db)):
    if not PlanService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Invitation ---
@router.get("/invitations", response_model=list[InvitationRead])
def list_invitations(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return InvitationService(db).list(limit=limit, offset=offset)

@router.get("/invitations/{id_}", response_model=InvitationRead)
def get_invitation(id_: int, db: Session = Depends(get_db)):
    obj = InvitationService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/invitations", response_model=InvitationRead, status_code=201)
def create_invitation(payload: InvitationCreate, db: Session = Depends(get_db)):
    obj = InvitationService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/invitations/{id_}", response_model=InvitationRead)
def update_invitation(id_: int, payload: InvitationUpdate, db: Session = Depends(get_db)):
    obj = InvitationService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/invitations/{id_}", status_code=204)
def delete_invitation(id_: int, db: Session = Depends(get_db)):
    if not InvitationService(db).delete(id_): raise HTTPException(404)
    db.commit()
