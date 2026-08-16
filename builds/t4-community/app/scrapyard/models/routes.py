"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import UserCreate, UserUpdate, UserRead, MembershipCreate, MembershipUpdate, MembershipRead, PostCreate, PostUpdate, PostRead
from .services import UserService, MembershipService, PostService
from scrapyard.database.db_session import get_db  # wired to the real session factory

router = APIRouter()

# --- User ---
@router.get("/users", response_model=list[UserRead])
def list_users(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return UserService(db).list(limit=limit, offset=offset)

@router.get("/users/{id_}", response_model=UserRead)
def get_user(id_: int, db: Session = Depends(get_db)):
    obj = UserService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/users", response_model=UserRead, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    obj = UserService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/users/{id_}", response_model=UserRead)
def update_user(id_: int, payload: UserUpdate, db: Session = Depends(get_db)):
    obj = UserService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/users/{id_}", status_code=204)
def delete_user(id_: int, db: Session = Depends(get_db)):
    if not UserService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Membership ---
@router.get("/memberships", response_model=list[MembershipRead])
def list_memberships(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return MembershipService(db).list(limit=limit, offset=offset)

@router.get("/memberships/{id_}", response_model=MembershipRead)
def get_membership(id_: int, db: Session = Depends(get_db)):
    obj = MembershipService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/memberships", response_model=MembershipRead, status_code=201)
def create_membership(payload: MembershipCreate, db: Session = Depends(get_db)):
    obj = MembershipService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/memberships/{id_}", response_model=MembershipRead)
def update_membership(id_: int, payload: MembershipUpdate, db: Session = Depends(get_db)):
    obj = MembershipService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/memberships/{id_}", status_code=204)
def delete_membership(id_: int, db: Session = Depends(get_db)):
    if not MembershipService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Post ---
@router.get("/posts", response_model=list[PostRead])
def list_posts(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return PostService(db).list(limit=limit, offset=offset)

@router.get("/posts/{id_}", response_model=PostRead)
def get_post(id_: int, db: Session = Depends(get_db)):
    obj = PostService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/posts", response_model=PostRead, status_code=201)
def create_post(payload: PostCreate, db: Session = Depends(get_db)):
    obj = PostService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/posts/{id_}", response_model=PostRead)
def update_post(id_: int, payload: PostUpdate, db: Session = Depends(get_db)):
    obj = PostService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/posts/{id_}", status_code=204)
def delete_post(id_: int, db: Session = Depends(get_db)):
    if not PostService(db).delete(id_): raise HTTPException(404)
    db.commit()
