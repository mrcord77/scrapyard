"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import ProjectCreate, ProjectUpdate, ProjectRead, TaskCreate, TaskUpdate, TaskRead, ChangeOrderCreate, ChangeOrderUpdate, ChangeOrderRead, DocumentCreate, DocumentUpdate, DocumentRead
from .services import ProjectService, TaskService, ChangeOrderService, DocumentService
from scrapyard.database.db_session import get_db  # wired to the real session factory

router = APIRouter()

# --- Project ---
@router.get("/projects", response_model=list[ProjectRead])
def list_projects(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return ProjectService(db).list(limit=limit, offset=offset)

@router.get("/projects/{id_}", response_model=ProjectRead)
def get_project(id_: int, db: Session = Depends(get_db)):
    obj = ProjectService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    obj = ProjectService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/projects/{id_}", response_model=ProjectRead)
def update_project(id_: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    obj = ProjectService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/projects/{id_}", status_code=204)
def delete_project(id_: int, db: Session = Depends(get_db)):
    if not ProjectService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Task ---
@router.get("/tasks", response_model=list[TaskRead])
def list_tasks(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return TaskService(db).list(limit=limit, offset=offset)

@router.get("/tasks/{id_}", response_model=TaskRead)
def get_task(id_: int, db: Session = Depends(get_db)):
    obj = TaskService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/tasks", response_model=TaskRead, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    obj = TaskService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/tasks/{id_}", response_model=TaskRead)
def update_task(id_: int, payload: TaskUpdate, db: Session = Depends(get_db)):
    obj = TaskService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/tasks/{id_}", status_code=204)
def delete_task(id_: int, db: Session = Depends(get_db)):
    if not TaskService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- ChangeOrder ---
@router.get("/change_orders", response_model=list[ChangeOrderRead])
def list_change_orders(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return ChangeOrderService(db).list(limit=limit, offset=offset)

@router.get("/change_orders/{id_}", response_model=ChangeOrderRead)
def get_change_order(id_: int, db: Session = Depends(get_db)):
    obj = ChangeOrderService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/change_orders", response_model=ChangeOrderRead, status_code=201)
def create_change_order(payload: ChangeOrderCreate, db: Session = Depends(get_db)):
    obj = ChangeOrderService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/change_orders/{id_}", response_model=ChangeOrderRead)
def update_change_order(id_: int, payload: ChangeOrderUpdate, db: Session = Depends(get_db)):
    obj = ChangeOrderService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/change_orders/{id_}", status_code=204)
def delete_change_order(id_: int, db: Session = Depends(get_db)):
    if not ChangeOrderService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Document ---
@router.get("/documents", response_model=list[DocumentRead])
def list_documents(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return DocumentService(db).list(limit=limit, offset=offset)

@router.get("/documents/{id_}", response_model=DocumentRead)
def get_document(id_: int, db: Session = Depends(get_db)):
    obj = DocumentService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/documents", response_model=DocumentRead, status_code=201)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db)):
    obj = DocumentService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/documents/{id_}", response_model=DocumentRead)
def update_document(id_: int, payload: DocumentUpdate, db: Session = Depends(get_db)):
    obj = DocumentService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/documents/{id_}", status_code=204)
def delete_document(id_: int, db: Session = Depends(get_db)):
    if not DocumentService(db).delete(id_): raise HTTPException(404)
    db.commit()
