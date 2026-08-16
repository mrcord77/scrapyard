"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import ProjectCreate, ProjectUpdate, ProjectRead, TaskCreate, TaskUpdate, TaskRead, LabelCreate, LabelUpdate, LabelRead
from .services import ProjectService, TaskService, LabelService
from .services import WorkflowError
from .services import TaskLabelsLinks
from .models import Project, Task
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

# --- Project ---
@router.get("/projects", response_model=list[ProjectRead])
def list_projects(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Project).where(Project.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/projects/{id_}", response_model=ProjectRead)
def get_project(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProjectService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = ProjectService(db).create(**data)
    db.commit(); return obj

@router.put("/projects/{id_}", response_model=ProjectRead)
def update_project(id_: int, payload: ProjectUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProjectService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = ProjectService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/projects/{id_}", status_code=204)
def delete_project(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProjectService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    ProjectService(db).delete(id_)
    db.commit()

@router.post("/projects/{id_}/transition", response_model=ProjectRead)
def transition_project(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = ProjectService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    try:
        obj = ProjectService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- Task ---
@router.get("/tasks", response_model=list[TaskRead])
def list_tasks(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Task).where(Task.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/tasks/{id_}", response_model=TaskRead)
def get_task(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = TaskService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/tasks", response_model=TaskRead, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = TaskService(db).create(**data)
    db.commit(); return obj

@router.put("/tasks/{id_}", response_model=TaskRead)
def update_task(id_: int, payload: TaskUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = TaskService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = TaskService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/tasks/{id_}", status_code=204)
def delete_task(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = TaskService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    TaskService(db).delete(id_)
    db.commit()

@router.post("/tasks/{id_}/transition", response_model=TaskRead)
def transition_task(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = TaskService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    try:
        obj = TaskService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- Label ---
@router.get("/labels", response_model=list[LabelRead])
def list_labels(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return LabelService(db).list(limit=limit, offset=offset)

@router.get("/labels/{id_}", response_model=LabelRead)
def get_label(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LabelService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/labels", response_model=LabelRead, status_code=201)
def create_label(payload: LabelCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LabelService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/labels/{id_}", response_model=LabelRead)
def update_label(id_: int, payload: LabelUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LabelService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/labels/{id_}", status_code=204)
def delete_label(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not LabelService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- data subject rights (GDPR/CCPA: access, portability, erasure) ---
@router.get("/privacy/export")
def privacy_export(db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    """Export everything stored about the authenticated user (domain + identity)."""
    from . import privacy as _p
    from scrapyard.compliance.data_export import export_user_data as _identity_export
    return {'user_id': uid, 'domain_data': _p.export_user_data(db, uid),
            'identity_data': _identity_export(db, uid)}

@router.get("/privacy/export/stream")
def privacy_export_stream(db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    """Stream the user's domain data as NDJSON (one record per line), constant-
    memory via a server-side cursor — portability that scales to large accounts
    without buffering the whole export in memory."""
    from fastapi.responses import StreamingResponse
    from . import privacy as _p
    return StreamingResponse(_p.stream_user_data(db, uid), media_type='application/x-ndjson',
                             headers={'Content-Disposition': 'attachment; filename="export.ndjson"'})

@router.post("/privacy/delete-account")
def privacy_delete_account(db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    """Erase the authenticated user: domain-owned rows first, then identity
    (sessions + user record), with an audit record. Right to erasure."""
    from . import privacy as _p
    from scrapyard.compliance.account_deletion import delete_account as _delete_identity
    domain = _p.delete_user_data(db, uid)   # domain tables (own ORM registry)
    identity = _delete_identity(db, uid)    # library identity tables + user row
    db.commit()
    return {'deleted': True, 'domain': domain, 'identity': identity}

# --- link: Task <-> Label (task_labels) ---
@router.post("/tasks/{id_}/labels/{rid}", status_code=201)
def attach_tasks_labels(id_: int, rid: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    TaskLabelsLinks(db).attach(id_, rid); db.commit(); return {'linked': True}

@router.delete("/tasks/{id_}/labels/{rid}", status_code=204)
def detach_tasks_labels(id_: int, rid: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    TaskLabelsLinks(db).detach(id_, rid); db.commit()

@router.get("/tasks/{id_}/labels", response_model=list[LabelRead])
def list_tasks_labels(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return TaskLabelsLinks(db).list_right(id_)
