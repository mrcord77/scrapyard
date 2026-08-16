"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import ResearchDocCreate, ResearchDocUpdate, ResearchDocRead, NoteCreate, NoteUpdate, NoteRead, ExperimentCreate, ExperimentUpdate, ExperimentRead, RunCreate, RunUpdate, RunRead, TagCreate, TagUpdate, TagRead
from .services import ResearchDocService, NoteService, ExperimentService, RunService, TagService
from .services import WorkflowError
from .services import ResearchDocTagsLinks, ExperimentTagsLinks
from .models import ResearchDoc, Note, Experiment, Run
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

# --- ResearchDoc ---
@router.get("/research_docs", response_model=list[ResearchDocRead])
def list_research_docs(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(ResearchDoc).where(ResearchDoc.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/research_docs/{id_}", response_model=ResearchDocRead)
def get_research_doc(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ResearchDocService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/research_docs", response_model=ResearchDocRead, status_code=201)
def create_research_doc(payload: ResearchDocCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = ResearchDocService(db).create(**data)
    db.commit(); return obj

@router.put("/research_docs/{id_}", response_model=ResearchDocRead)
def update_research_doc(id_: int, payload: ResearchDocUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ResearchDocService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = ResearchDocService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/research_docs/{id_}", status_code=204)
def delete_research_doc(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ResearchDocService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    ResearchDocService(db).delete(id_)
    db.commit()

@router.post("/research_docs/{id_}/transition", response_model=ResearchDocRead)
def transition_research_doc(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = ResearchDocService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    try:
        obj = ResearchDocService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- Note ---
@router.get("/notes", response_model=list[NoteRead])
def list_notes(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Note).where(Note.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/notes/{id_}", response_model=NoteRead)
def get_note(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = NoteService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/notes", response_model=NoteRead, status_code=201)
def create_note(payload: NoteCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = NoteService(db).create(**data)
    db.commit(); return obj

@router.put("/notes/{id_}", response_model=NoteRead)
def update_note(id_: int, payload: NoteUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = NoteService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = NoteService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/notes/{id_}", status_code=204)
def delete_note(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = NoteService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    NoteService(db).delete(id_)
    db.commit()

# --- Experiment ---
@router.get("/experiments", response_model=list[ExperimentRead])
def list_experiments(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Experiment).where(Experiment.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/experiments/{id_}", response_model=ExperimentRead)
def get_experiment(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ExperimentService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/experiments", response_model=ExperimentRead, status_code=201)
def create_experiment(payload: ExperimentCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = ExperimentService(db).create(**data)
    db.commit(); return obj

@router.put("/experiments/{id_}", response_model=ExperimentRead)
def update_experiment(id_: int, payload: ExperimentUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ExperimentService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = ExperimentService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/experiments/{id_}", status_code=204)
def delete_experiment(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ExperimentService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    ExperimentService(db).delete(id_)
    db.commit()

@router.post("/experiments/{id_}/transition", response_model=ExperimentRead)
def transition_experiment(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = ExperimentService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    try:
        obj = ExperimentService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- Run ---
@router.get("/runs", response_model=list[RunRead])
def list_runs(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Run).where(Run.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/runs/{id_}", response_model=RunRead)
def get_run(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = RunService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/runs", response_model=RunRead, status_code=201)
def create_run(payload: RunCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = RunService(db).create(**data)
    db.commit(); return obj

@router.put("/runs/{id_}", response_model=RunRead)
def update_run(id_: int, payload: RunUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = RunService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = RunService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/runs/{id_}", status_code=204)
def delete_run(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = RunService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    RunService(db).delete(id_)
    db.commit()

@router.post("/runs/{id_}/transition", response_model=RunRead)
def transition_run(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = RunService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    try:
        obj = RunService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- Tag ---
@router.get("/tags", response_model=list[TagRead])
def list_tags(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return TagService(db).list(limit=limit, offset=offset)

@router.get("/tags/{id_}", response_model=TagRead)
def get_tag(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = TagService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/tags", response_model=TagRead, status_code=201)
def create_tag(payload: TagCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = TagService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/tags/{id_}", response_model=TagRead)
def update_tag(id_: int, payload: TagUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = TagService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/tags/{id_}", status_code=204)
def delete_tag(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not TagService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- data subject rights (GDPR/CCPA: access, portability, erasure) ---
# Module-scope import so DeletionRecord registers on the ORM base BEFORE the
# boot-time create_all — a lazy in-route import would leave its table missing.
import scrapyard.compliance.account_deletion  # noqa: F401  (model registration)
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
    # confirm=True: without it delete_account is a SAFE-BY-DEFAULT dry run and
    # the user row + sessions would survive (deleted account could log back in).
    identity = _delete_identity(db, uid, confirm=True)  # library identity tables + user row
    db.commit()
    return {'deleted': True, 'domain': domain, 'identity': identity}

# --- link: ResearchDoc <-> Tag (research_doc_tags) ---
@router.post("/research_docs/{id_}/tags/{rid}", status_code=201)
def attach_research_docs_tags(id_: int, rid: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    ResearchDocTagsLinks(db).attach(id_, rid); db.commit(); return {'linked': True}

@router.delete("/research_docs/{id_}/tags/{rid}", status_code=204)
def detach_research_docs_tags(id_: int, rid: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    ResearchDocTagsLinks(db).detach(id_, rid); db.commit()

@router.get("/research_docs/{id_}/tags", response_model=list[TagRead])
def list_research_docs_tags(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return ResearchDocTagsLinks(db).list_right(id_)

# --- link: Experiment <-> Tag (experiment_tags) ---
@router.post("/experiments/{id_}/tags/{rid}", status_code=201)
def attach_experiments_tags(id_: int, rid: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    ExperimentTagsLinks(db).attach(id_, rid); db.commit(); return {'linked': True}

@router.delete("/experiments/{id_}/tags/{rid}", status_code=204)
def detach_experiments_tags(id_: int, rid: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    ExperimentTagsLinks(db).detach(id_, rid); db.commit()

@router.get("/experiments/{id_}/tags", response_model=list[TagRead])
def list_experiments_tags(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return ExperimentTagsLinks(db).list_right(id_)
